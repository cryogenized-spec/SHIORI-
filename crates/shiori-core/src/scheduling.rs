//! Local-only deterministic time-block proposals.
//!
//! This module never edits task records or contacts a calendar provider.
//! Callers must supply real UTC availability and busy intervals. Timezone-aware
//! construction of those intervals belongs at the client boundary.
use crate::Priority;
use chrono::{DateTime, Duration, NaiveDate, Utc};
use std::collections::{HashMap, HashSet};
use thiserror::Error;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Interval {
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
}

impl Interval {
    pub fn new(start: DateTime<Utc>, end: DateTime<Utc>) -> Result<Self, PlanError> {
        if start >= end {
            return Err(PlanError::InvalidInterval);
        }
        Ok(Self { start, end })
    }
}

#[derive(Debug, Clone)]
pub struct PlanningTask {
    pub id: String,
    pub title: String,
    pub priority: Priority,
    pub due_on: Option<NaiveDate>,
    pub minutes: i64,
    /// IDs must be completed already or appear earlier in this preview.
    pub dependencies: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct PlanRequest {
    pub day: NaiveDate,
    pub tasks: Vec<PlanningTask>,
    pub completed_ids: Vec<String>,
    pub availability: Vec<Interval>,
    pub busy: Vec<Interval>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlannedBlock {
    pub task_id: String,
    pub title: String,
    pub start: DateTime<Utc>,
    pub end: DateTime<Utc>,
    pub overdue: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UnscheduledReason {
    NoCapacity,
    BlockedByDependency,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UnscheduledTask {
    pub task_id: String,
    pub reason: UnscheduledReason,
}

#[derive(Debug, Clone)]
pub struct PlanPreview {
    pub blocks: Vec<PlannedBlock>,
    pub unscheduled: Vec<UnscheduledTask>,
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum PlanError {
    #[error("availability and busy intervals must have start before end")]
    InvalidInterval,
    #[error("each task needs a unique non-empty id")]
    InvalidTaskId,
    #[error("duration must be greater than zero for task {0}")]
    InvalidDuration(String),
}

fn rank(priority: Priority) -> u8 {
    match priority {
        Priority::Urgent => 4,
        Priority::High => 3,
        Priority::Medium => 2,
        Priority::Low => 1,
    }
}

fn find_free(
    availability: &[Interval],
    reserved: &[Interval],
    earliest: Option<DateTime<Utc>>,
    minutes: i64,
) -> Option<Interval> {
    let length = Duration::minutes(minutes);
    for window in availability {
        let mut cursor = earliest
            .map(|time| time.max(window.start))
            .unwrap_or(window.start);
        loop {
            let Some(end) = cursor.checked_add_signed(length) else {
                break;
            };
            if end > window.end {
                break;
            }
            let overlap = reserved
                .iter()
                .filter(|occupied| occupied.start < end && occupied.end > cursor)
                .min_by_key(|occupied| occupied.start);
            if let Some(occupied) = overlap {
                cursor = occupied.end;
            } else {
                return Some(Interval { start: cursor, end });
            }
        }
    }
    None
}

/// Greedy, deterministic and side-effect free. Prioritises urgent tasks, then
/// calendar due day, then task ID. Dependencies finish before dependants start.
/// No capacity is silently invented: overflow is returned explicitly.
pub fn plan_day(mut request: PlanRequest) -> Result<PlanPreview, PlanError> {
    for interval in request.availability.iter().chain(&request.busy) {
        if interval.start >= interval.end {
            return Err(PlanError::InvalidInterval);
        }
    }
    let mut seen = HashSet::new();
    for task in &request.tasks {
        if task.id.trim().is_empty() || !seen.insert(task.id.as_str()) {
            return Err(PlanError::InvalidTaskId);
        }
        if task.minutes <= 0 || Duration::try_minutes(task.minutes).is_none() {
            return Err(PlanError::InvalidDuration(task.id.clone()));
        }
    }
    request.availability.sort_by_key(|window| window.start);
    let mut remaining = request.tasks;
    remaining.sort_by(|a, b| {
        rank(b.priority)
            .cmp(&rank(a.priority))
            .then(a.due_on.cmp(&b.due_on))
            .then(a.id.cmp(&b.id))
    });

    let completed: HashSet<String> = request.completed_ids.into_iter().collect();
    let mut ends: HashMap<String, DateTime<Utc>> = HashMap::new();
    let mut reserved = request.busy;
    let mut blocks = Vec::new();
    let mut unscheduled = Vec::new();
    while !remaining.is_empty() {
        let ready_index = remaining.iter().position(|task| {
            task.dependencies
                .iter()
                .all(|dependency| completed.contains(dependency) || ends.contains_key(dependency))
        });
        let Some(index) = ready_index else {
            unscheduled.extend(remaining.drain(..).map(|task| UnscheduledTask {
                task_id: task.id,
                reason: UnscheduledReason::BlockedByDependency,
            }));
            break;
        };
        let task = remaining.remove(index);
        let earliest = task
            .dependencies
            .iter()
            .filter_map(|dependency| ends.get(dependency))
            .max()
            .cloned();
        if let Some(slot) = find_free(&request.availability, &reserved, earliest, task.minutes) {
            ends.insert(task.id.clone(), slot.end);
            blocks.push(PlannedBlock {
                task_id: task.id,
                title: task.title,
                start: slot.start,
                end: slot.end,
                overdue: task.due_on.is_some_and(|due| due < request.day),
            });
            reserved.push(slot);
        } else {
            unscheduled.push(UnscheduledTask {
                task_id: task.id,
                reason: UnscheduledReason::NoCapacity,
            });
        }
    }
    blocks.sort_by(|a, b| a.start.cmp(&b.start).then(a.task_id.cmp(&b.task_id)));
    unscheduled.sort_by(|a, b| a.task_id.cmp(&b.task_id));
    Ok(PlanPreview { blocks, unscheduled })
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn at(hour: u32, minute: u32) -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 11, 12, hour, minute, 0)
            .single()
            .unwrap()
    }
    fn task(id: &str, priority: Priority, mins: i64) -> PlanningTask {
        PlanningTask {
            id: id.to_owned(),
            title: id.to_owned(),
            priority,
            due_on: None,
            minutes: mins,
            dependencies: Vec::new(),
        }
    }
    fn request(tasks: Vec<PlanningTask>) -> PlanRequest {
        PlanRequest {
            day: NaiveDate::from_ymd_opt(2026, 11, 12).unwrap(),
            tasks,
            completed_ids: vec![],
            availability: vec![Interval::new(at(8, 0), at(12, 0)).unwrap()],
            busy: vec![Interval::new(at(9, 0), at(10, 0)).unwrap()],
        }
    }

    #[test]
    fn honours_busy_time_priority_and_overflow() {
        let planned = plan_day(request(vec![
            task("low", Priority::Low, 60),
            task("urgent", Priority::Urgent, 60),
            task("medium", Priority::Medium, 150),
        ]))
        .unwrap();
        assert_eq!(planned.blocks.len(), 2);
        assert_eq!(planned.blocks[0].task_id, "urgent");
        assert_eq!(planned.blocks[0].start, at(8, 0));
        assert_eq!(planned.blocks[1].task_id, "low");
        assert_eq!(planned.blocks[1].start, at(10, 0));
        assert_eq!(
            planned.unscheduled,
            vec![UnscheduledTask {
                task_id: "medium".into(),
                reason: UnscheduledReason::NoCapacity,
            }]
        );
    }

    #[test]
    fn dependencies_are_after_prerequisites_even_if_more_urgent() {
        let mut dependent = task("finish", Priority::Urgent, 30);
        dependent.dependencies.push("prepare".into());
        let planned = plan_day(request(vec![
            dependent,
            task("prepare", Priority::Low, 30),
        ]))
        .unwrap();
        assert_eq!(planned.blocks[0].task_id, "prepare");
        assert_eq!(planned.blocks[1].task_id, "finish");
        assert_eq!(planned.blocks[1].start, planned.blocks[0].end);
        assert!(planned.unscheduled.is_empty());
    }

    #[test]
    fn missing_prerequisites_and_cycles_are_reported_not_dropped() {
        let mut a = task("a", Priority::High, 30);
        a.dependencies.push("b".into());
        let mut b = task("b", Priority::Low, 30);
        b.dependencies.push("a".into());
        let mut c = task("c", Priority::Low, 30);
        c.dependencies.push("unknown".into());
        let planned = plan_day(request(vec![a, b, c])).unwrap();
        assert!(planned.blocks.is_empty());
        assert_eq!(planned.unscheduled.len(), 3);
        assert!(planned.unscheduled.iter().all(|task| {
            task.reason == UnscheduledReason::BlockedByDependency
        }));
    }

    #[test]
    fn invalid_inputs_are_rejected() {
        assert_eq!(
            plan_day(request(vec![task("x", Priority::Low, 0)])).unwrap_err(),
            PlanError::InvalidDuration("x".into())
        );
        assert_eq!(
            plan_day(request(vec![
                task("same", Priority::Low, 30),
                task("same", Priority::High, 30),
            ])).unwrap_err(),
            PlanError::InvalidTaskId
        );
    }

    #[test]
    fn completed_predecessor_allows_planning() {
        let mut req = request(vec![{
            let mut t = task("after", Priority::Low, 30);
            t.dependencies.push("already-done".into());
            t
        }]);
        req.completed_ids.push("already-done".into());
        let plan = plan_day(req).unwrap();
        assert_eq!(plan.blocks.len(), 1);
        assert!(plan.unscheduled.is_empty());
    }
}
