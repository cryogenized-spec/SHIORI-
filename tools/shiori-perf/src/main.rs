//! Repeatable local benchmark probe for CI and developer diagnostics.
//! No telemetry, no network requests, and no user task data are collected.
use chrono::NaiveDate;
use shiori_core::{Priority, Task};
use shiori_storage::{SqliteStore, TaskFilter};
use std::{env, error::Error, time::Instant};

const DEFAULT_ROWS: usize = 3_000;
const QUERY_SAMPLES: usize = 40;

struct Measurement {
    name: &'static str,
    samples_ms: Vec<f64>,
}

impl Measurement {
    fn capture<F: FnMut() -> Result<(), Box<dyn Error>>>(
        name: &'static str,
        samples: usize,
        mut operation: F,
    ) -> Result<Self, Box<dyn Error>> {
        // Discard warmup timing to reduce compilation/cold-cache artifacts.
        for _ in 0..5 {
            operation()?;
        }
        let mut samples_ms = Vec::with_capacity(samples);
        for _ in 0..samples {
            let start = Instant::now();
            operation()?;
            samples_ms.push(start.elapsed().as_secs_f64() * 1_000.0);
        }
        samples_ms.sort_by(f64::total_cmp);
        Ok(Self { name, samples_ms })
    }

    fn percentile(&self, percent: usize) -> f64 {
        let index = ((self.samples_ms.len() - 1) * percent).div_ceil(100);
        self.samples_ms[index.min(self.samples_ms.len() - 1)]
    }

    fn as_json(&self) -> String {
        format!(
            "{{\"name\":\"{}\",\"unit\":\"ms\",\"samples\":{},\"p50\":{:.5},\"p95\":{:.5},\"p99\":{:.5}}}",
            self.name,
            self.samples_ms.len(),
            self.percentile(50),
            self.percentile(95),
            self.percentile(99)
        )
    }
}

fn parse_rows() -> Result<usize, Box<dyn Error>> {
    let mut args = env::args().skip(1);
    match (args.next().as_deref(), args.next(), args.next()) {
        (None, None, None) => Ok(DEFAULT_ROWS),
        (Some("--rows"), Some(rows), None) => {
            let rows: usize = rows.parse()?;
            if !(100..=100_000).contains(&rows) {
                return Err("--rows must be between 100 and 100000".into());
            }
            Ok(rows)
        }
        _ => Err("usage: shiori-perf [--rows 3000]".into()),
    }
}

fn main() -> Result<(), Box<dyn Error>> {
    let rows = parse_rows()?;
    let start = Instant::now();
    let store = SqliteStore::in_memory()?;
    let startup_ms = start.elapsed().as_secs_f64() * 1_000.0;
    let due_base = NaiveDate::from_ymd_opt(2026, 11, 1).ok_or("invalid fixture date")?;
    let mut picked = String::new();

    for i in 0..rows {
        let title = format!("Benchmark task {i:06} {}", if i % 31 == 0 { "needle" } else { "routine" });
        let project = if i % 3 == 0 { "Core" } else { "Personal" };
        let priority = if i % 10 == 0 { Priority::High } else { Priority::Medium };
        let due = due_base + chrono::Duration::days((i % 30) as i64);
        let task = Task::new(&title, project, priority, Some(due))?;
        if i == rows / 2 { picked = task.id.clone(); }
        store.insert(&task)?;
    }

    let mut measurements = Vec::new();
    measurements.push(Measurement::capture("point_lookup", QUERY_SAMPLES, || {
        std::hint::black_box(store.get(&picked)?);
        Ok(())
    })?);
    measurements.push(Measurement::capture("project_filter", QUERY_SAMPLES, || {
        let result = store.list(TaskFilter { project: Some("Core"), ..Default::default() })?;
        assert!(!result.is_empty());
        std::hint::black_box(result);
        Ok(())
    })?);
    measurements.push(Measurement::capture("due_filter", QUERY_SAMPLES, || {
        let result = store.list(TaskFilter {
            due_on_or_before: Some(due_base + chrono::Duration::days(4)),
            ..Default::default()
        })?;
        assert!(!result.is_empty());
        std::hint::black_box(result);
        Ok(())
    })?);
    measurements.push(Measurement::capture("text_search", QUERY_SAMPLES, || {
        let result = store.list(TaskFilter { search: Some("needle"), ..Default::default() })?;
        assert!(!result.is_empty());
        std::hint::black_box(result);
        Ok(())
    })?);
    let timings = measurements.iter().map(Measurement::as_json).collect::<Vec<_>>().join(",");
    println!("{{\"schema\":1,\"benchmark\":\"sqlite_local_tasks\",\"dataset_rows\":{rows},\"database_open_ms\":{startup_ms:.5},\"measurements\":[{timings}]}}");
    Ok(())
}
