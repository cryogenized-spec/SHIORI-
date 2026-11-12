//! Explicit, non-destructive conversion of Android WebView backup records into
//! canonical SHIORI Task rows, *without* making the target authoritative.
//! The entire original JSON (including tags, saved views and sort settings)
//! is archived transactionally next to the imported rows for lossless recovery.
use chrono::{DateTime, NaiveDate, Utc};
use serde_json::Value;
use shiori_core::{Priority, Task, TaskStatus, validate_assignee_id};
use shiori_storage::{SqliteStore, TaskFilter};
use std::{error::Error, path::Path, str::FromStr};

use crate::validate_snapshot;

#[derive(Debug, PartialEq, Eq)]
pub struct ShadowReport {
    pub imported: usize,
    /// False when the exact same input had previously been staged.
    pub created: bool,
    /// Timestamps inferred from existing data because the legacy field is absent.
    pub inferred_timestamps: usize,
}

fn timestamp(s: &str) -> Result<DateTime<Utc>, Box<dyn Error>> {
    Ok(DateTime::parse_from_rfc3339(s)?.with_timezone(&Utc))
}

/// Converts a legacy Android JSON snapshot and archives that exact source.
/// A failure never partially imports tasks, nor changes the WebView database.
pub fn stage_legacy_backup(db_path: &Path, raw: &str) -> Result<ShadowReport, Box<dyn Error>> {
    validate_snapshot(raw)?;
    let mut store = SqliteStore::open(db_path)?;

    // Browser JSON exports include a newly generated exported_at on every
    // invocation. Treat an identical task/view snapshot with only this
    // timestamp changed as the same import; keep the originally archived
    // bytes, so another tap on Stage is safely idempotent.
    let previous = store.legacy_shadow_source()?;
    let chosen_source = if let Some(previous) = &previous {
        let mut old: Value = serde_json::from_str(previous)?;
        let mut current: Value = serde_json::from_str(raw)?;
        if let (Some(old), Some(current)) = (old.as_object_mut(), current.as_object_mut()) {
            old.remove("exported_at");
            current.remove("exported_at");
        }
        if old == current {
            previous.as_str()
        } else {
            raw
        }
    } else {
        raw
    };
    let snapshot: Value = serde_json::from_str(chosen_source)?;
    let root = snapshot
        .as_object()
        .ok_or("backup root must be an object")?;
    let data = root
        .get("tasks")
        .and_then(Value::as_array)
        .ok_or("missing legacy task collection")?;
    let exported = root
        .get("exported_at")
        .and_then(Value::as_str)
        .map(timestamp)
        .transpose()?;
    let fallback = exported.unwrap_or_else(Utc::now);
    let mut inferred_timestamps = 0;
    let mut converted = Vec::with_capacity(data.len());
    for legacy in data {
        let map = legacy.as_object().ok_or("invalid legacy task object")?;
        let required = |key: &str| -> Result<&str, Box<dyn Error>> {
            Ok(map
                .get(key)
                .and_then(Value::as_str)
                .ok_or("missing task field")?)
        };
        let due = map.get("due").and_then(Value::as_str).unwrap_or("");
        let due_on = if due.is_empty() {
            None
        } else {
            Some(NaiveDate::parse_from_str(due, "%Y-%m-%d")?)
        };
        let priority = Priority::from_str(required("priority")?)?;
        let mut task = Task::new(required("title")?, required("project")?, priority, due_on)?;
        // Old Android-created IDs can be "u<timestamp>" rather than UUIDv7.
        // Preserve identity instead of inventing a new UUID and breaking links.
        task.id = required("id")?.to_owned();
        task.notes = map
            .get("description")
            .and_then(Value::as_str)
            .unwrap_or("")
            .to_owned();
        task.status = match required("status")? {
            "todo" => TaskStatus::Todo,
            "progress" => TaskStatus::InProgress,
            "done" => TaskStatus::Done,
            _ => return Err("unsupported legacy task state".into()),
        };
        task.estimate_minutes = map.get("mins").and_then(Value::as_i64);
        task.assignee_id = map
            .get("assigneeId")
            .and_then(Value::as_str)
            .map(validate_assignee_id)
            .transpose()?;

        task.created_at = if let Some(raw_created) = map.get("createdAt").and_then(Value::as_str) {
            timestamp(raw_created)?
        } else {
            inferred_timestamps += 1;
            fallback
        };
        task.updated_at = if let Some(raw_updated) = map.get("updatedAt").and_then(Value::as_str) {
            timestamp(raw_updated)?
        } else {
            inferred_timestamps += 1;
            task.created_at
        };
        task.version = if let Some(value) = map.get("version").filter(|v| !v.is_null()) {
            let v = value.as_i64().ok_or("invalid task revision")?;
            if v < 1 {
                return Err("invalid task revision".into());
            }
            v
        } else {
            1
        };
        task.completed_at = if task.status == TaskStatus::Done {
            if let Some(raw_completed) = map.get("completedAt").and_then(Value::as_str) {
                Some(timestamp(raw_completed)?)
            } else {
                inferred_timestamps += 1;
                Some(task.updated_at)
            }
        } else {
            None
        };
        // Every new canonical row starts active; the original snapshot
        // remains intact in the shadow sidecar, including all extra fields.
        converted.push(task);
    }

    let created = store.stage_legacy_shadow(&converted, chosen_source)?;
    let rows = store.list(TaskFilter::default())?;
    if rows.len() != converted.len() {
        return Err("shadow read-back count mismatch".into());
    }
    for imported in &converted {
        let current = store.get(&imported.id)?;
        if current.title != imported.title
            || current.notes != imported.notes
            || current.status != imported.status
            || current.version != imported.version
            || current.due_on != imported.due_on
            || current.assignee_id != imported.assignee_id
            || current.estimate_minutes != imported.estimate_minutes
            || current.created_at != imported.created_at
            || current.updated_at != imported.updated_at
        {
            return Err("shadow read-back task mismatch".into());
        }
    }
    if store.legacy_shadow_source()?.as_deref() != Some(chosen_source) {
        return Err("original source backup was not archived".into());
    }
    Ok(ShadowReport {
        imported: converted.len(),
        created,
        inferred_timestamps,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn target() -> PathBuf {
        std::env::temp_dir().join(format!(
            "shiori-android-shadow-{}-{}.sqlite3",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ))
    }

    fn sample() -> String {
        serde_json::json!({
            "format":"shiori-android-local-v1",
            "exported_at":"2026-11-12T18:00:00Z",
            "tasks":[
                {"id":"u1700000000","title":"栞 review café",
                 "description":"Multiline\nlong-lived notes","project":"Android",
                 "priority":"high","status":"progress",
                 "createdAt":"2026-11-11T12:34:56Z",
                 "due":"2026-11-15","mins":40,
                 "tags":["local","special"],"version":4},
                {"id":"u1700000001","title":"Complete project",
                 "description":"","project":"Work","priority":"urgent",
                 "status":"done","assigneeId":"local","tags":[],"due":""}
            ],
            "saved_views":[{"name":"Priority queue","view":"attention","filter":"high",
                "sort":"fifo","query":"review"}],
            "sort":"fifo"
        })
        .to_string()
    }

    #[test]
    fn shadow_preserves_ids_status_timestamps_and_original_json() {
        let path = target();
        let raw = sample();
        let report = stage_legacy_backup(&path, &raw).unwrap();
        assert_eq!(report.imported, 2);
        assert!(report.created);
        assert_eq!(report.inferred_timestamps, 4);
        let store = SqliteStore::open(&path).unwrap();
        let active = store.get("u1700000000").unwrap();
        assert_eq!(active.status, TaskStatus::InProgress);
        assert_eq!(active.version, 4);
        assert_eq!(active.estimate_minutes, Some(40));
        assert_eq!(active.notes, "Multiline\nlong-lived notes");
        let done = store.get("u1700000001").unwrap();
        assert_eq!(done.status, TaskStatus::Done);
        assert_eq!(done.assignee_id.as_deref(), Some("local"));
        assert!(done.completed_at.is_some());
        assert_eq!(store.legacy_shadow_source().unwrap(), Some(raw.clone()));
        assert_eq!(stage_legacy_backup(&path, &raw).unwrap().created, false);
        let mut reexport: Value = serde_json::from_str(&raw).unwrap();
        reexport["exported_at"] = Value::from("2026-11-12T20:15:00Z");
        assert!(
            !stage_legacy_backup(&path, &reexport.to_string())
                .unwrap()
                .created
        );
        let mut changed: Value = serde_json::from_str(&raw).unwrap();
        changed["tasks"][0]["title"] = Value::from("Newer record");
        assert!(stage_legacy_backup(&path, &changed.to_string()).is_err());
        assert_eq!(store.legacy_shadow_source().unwrap(), Some(raw));
        assert_eq!(store.get("u1700000000").unwrap().title, "栞 review café");
        drop(store);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn bad_source_never_imports_partial_records() {
        let path = target();
        let mut data: Value = serde_json::from_str(&sample()).unwrap();
        data["tasks"][1]["createdAt"] = Value::from("not a timestamp");
        assert!(stage_legacy_backup(&path, &data.to_string()).is_err());
        let store = SqliteStore::open(&path).unwrap();
        assert!(store.list(TaskFilter::default()).unwrap().is_empty());
        assert!(store.legacy_shadow_source().unwrap().is_none());
        drop(store);
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn nonempty_canonical_target_is_not_overwritten() {
        let path = target();
        let store = SqliteStore::open(&path).unwrap();
        let sentinel = Task::new("Pre-existing", "Core", Priority::Low, None).unwrap();
        store.insert(&sentinel).unwrap();
        assert!(stage_legacy_backup(&path, &sample()).is_err());
        let store = SqliteStore::open(&path).unwrap();
        assert_eq!(store.list(TaskFilter::default()).unwrap().len(), 1);
        assert!(store.legacy_shadow_source().unwrap().is_none());
        drop(store);
        std::fs::remove_file(path).unwrap();
    }
}
