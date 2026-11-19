//! SHIORI's platform-independent task model.
//! No filesystem, database, MCP, HTTP or UI dependencies belong here.

pub mod inbox;
pub mod scheduling;
pub mod spatial;

use jiff::{Timestamp, civil::Date};
use serde::{Deserialize, Serialize};
use std::str::FromStr;
use thiserror::Error;
use uuid::Uuid;

/// Preserve the legacy SQLite UTC offset spelling while storing Jiff instants.
/// Both `Z` and `+00:00` denote UTC; existing rows are parsed either way.
pub fn utc_rfc3339(ts: Timestamp) -> String {
    format!("{}+00:00", ts.to_string().trim_end_matches('Z'))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Priority {
    Low,
    Medium,
    High,
    Urgent,
}

impl Priority {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Low => "low",
            Self::Medium => "medium",
            Self::High => "high",
            Self::Urgent => "urgent",
        }
    }
}

impl FromStr for Priority {
    type Err = TaskError;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "low" => Ok(Self::Low),
            "medium" => Ok(Self::Medium),
            "high" => Ok(Self::High),
            "urgent" => Ok(Self::Urgent),
            _ => Err(TaskError::InvalidPriority),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Todo,
    InProgress,
    Done,
}

impl TaskStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Todo => "todo",
            Self::InProgress => "in_progress",
            Self::Done => "done",
        }
    }
}

impl FromStr for TaskStatus {
    type Err = TaskError;
    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "todo" => Ok(Self::Todo),
            "in_progress" => Ok(Self::InProgress),
            "done" => Ok(Self::Done),
            _ => Err(TaskError::InvalidStatus),
        }
    }
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum TaskError {
    #[error("task title cannot be empty")]
    EmptyTitle,
    #[error("task title is too long (maximum 160 characters)")]
    TitleTooLong,
    #[error("project name cannot be empty")]
    EmptyProject,
    #[error("synchronized notes exceed the permitted 8192 characters")]
    SyncedNotesTooLong,
    #[error("invalid priority")]
    InvalidPriority,
    #[error("invalid task status")]
    InvalidStatus,
    #[error("estimate must be between 1 and 1440 minutes")]
    InvalidEstimate,
    #[error("assignee ID must be 1–64 URL-safe ASCII characters")]
    InvalidAssignee,
}

pub fn validate_estimate(minutes: i64) -> Result<i64, TaskError> {
    if !(1..=1440).contains(&minutes) {
        return Err(TaskError::InvalidEstimate);
    }
    Ok(minutes)
}

pub fn validate_assignee_id(value: &str) -> Result<String, TaskError> {
    let id = value.trim();
    if id.is_empty()
        || id.len() > 64
        || !id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"-_.:".contains(&c))
    {
        return Err(TaskError::InvalidAssignee);
    }
    Ok(id.to_owned())
}

pub fn validate_project(value: &str) -> Result<String, TaskError> {
    let project = value.trim();
    if project.is_empty() {
        return Err(TaskError::EmptyProject);
    }
    Ok(project.to_owned())
}

/// A partial task edit. `None` means leave a field unchanged; `Some(None)`
/// explicitly clears the optional due date.
#[derive(Debug, Default)]
pub struct TaskPatch {
    pub title: Option<String>,
    pub notes: Option<String>,
    pub project: Option<String>,
    pub priority: Option<Priority>,
    pub due_on: Option<Option<Date>>,
    pub estimate_minutes: Option<Option<i64>>,
    /// None leaves assignee unchanged; Some(None) makes task unassigned.
    pub assignee_id: Option<Option<String>>,
}

pub fn validate_title(value: &str) -> Result<String, TaskError> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Err(TaskError::EmptyTitle);
    }
    if trimmed.chars().count() > 160 {
        return Err(TaskError::TitleTooLong);
    }
    Ok(trimmed.to_owned())
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Task {
    pub id: String,
    pub title: String,
    pub notes: String,
    pub project: String,
    pub priority: Priority,
    pub status: TaskStatus,
    /// A calendar date, not a UTC midnight timestamp.
    pub due_on: Option<Date>,
    /// Optional effort estimate in whole minutes. A missing estimate is not zero.
    #[serde(default)]
    pub estimate_minutes: Option<i64>,
    /// Opaque local assignment identity, distinct from authentication.
    #[serde(default)]
    pub assignee_id: Option<String>,
    pub created_at: Timestamp,
    pub updated_at: Timestamp,
    pub completed_at: Option<Timestamp>,
    /// Incremented on every mutation; base for future conflict detection.
    pub version: i64,
    /// Tombstones preserve deletions for eventual synchronization.
    pub deleted_at: Option<Timestamp>,
}

impl Task {
    pub fn new(
        title: &str,
        project: &str,
        priority: Priority,
        due_on: Option<Date>,
    ) -> Result<Self, TaskError> {
        let title = validate_title(title)?;
        let project = validate_project(project)?;
        let now = Timestamp::now();
        Ok(Self {
            id: Uuid::now_v7().to_string(),
            title,
            notes: String::new(),
            project,
            priority,
            status: TaskStatus::Todo,
            due_on,
            estimate_minutes: None,
            assignee_id: None,
            created_at: now,
            updated_at: now,
            completed_at: None,
            version: 1,
            deleted_at: None,
        })
    }

    pub fn change_status(&mut self, status: TaskStatus) {
        self.status = status;
        self.completed_at = if status == TaskStatus::Done {
            Some(Timestamp::now())
        } else {
            None
        };
        self.bump();
    }

    pub fn rename(&mut self, title: &str) -> Result<(), TaskError> {
        self.title = validate_title(title)?;
        self.bump();
        Ok(())
    }

    /// Validate all requested fields before applying any mutation. A no-op edit
    /// must not advance the revision, which is important for future sync.
    pub fn apply_patch(&mut self, patch: TaskPatch) -> Result<bool, TaskError> {
        let TaskPatch {
            title,
            notes,
            project,
            priority,
            due_on,
            estimate_minutes,
            assignee_id,
        } = patch;
        let title = title.as_deref().map(validate_title).transpose()?;
        let project = project.as_deref().map(validate_project).transpose()?;
        if let Some(Some(minutes)) = estimate_minutes {
            validate_estimate(minutes)?;
        }
        let assignee_id = assignee_id
            .map(|id| id.as_deref().map(validate_assignee_id).transpose())
            .transpose()?;
        let changed = title.as_ref().is_some_and(|value| value != &self.title)
            || notes.as_ref().is_some_and(|value| value != &self.notes)
            || project.as_ref().is_some_and(|value| value != &self.project)
            || priority.is_some_and(|value| value != self.priority)
            || due_on.is_some_and(|value| value != self.due_on)
            || estimate_minutes.is_some_and(|value| value != self.estimate_minutes)
            || assignee_id
                .as_ref()
                .is_some_and(|value| value != &self.assignee_id);
        if !changed {
            return Ok(false);
        }

        if let Some(value) = title {
            self.title = value;
        }
        if let Some(value) = notes {
            self.notes = value;
        }
        if let Some(value) = project {
            self.project = value;
        }
        if let Some(value) = priority {
            self.priority = value;
        }
        if let Some(value) = due_on {
            self.due_on = value;
        }
        if let Some(value) = estimate_minutes {
            self.estimate_minutes = value;
        }
        if let Some(value) = assignee_id {
            self.assignee_id = value;
        }
        self.bump();
        Ok(true)
    }

    /// Apply a validated common-field projection in *one* local revision.
    ///
    /// Intended only after a separately authenticated S2-origin receipt,
    /// verified S4 snapshot, explicit user review and backup. This is a pure
    /// domain operation: it does NOT authenticate Cloudflare or start syncing.
    /// Local-only due dates, estimates, assignees and creation times survive.
    /// Status transitions preserve their existing completion-time semantics.
    pub fn apply_reviewed_remote_common_fields(
        &mut self,
        title: &str,
        notes: &str,
        project: &str,
        priority: Priority,
        status: TaskStatus,
    ) -> Result<bool, TaskError> {
        let title = validate_title(title)?;
        let project = validate_project(project)?;
        if notes.chars().count() > 8192 {
            return Err(TaskError::SyncedNotesTooLong);
        }
        let changed = self.title != title
            || self.notes != notes
            || self.project != project
            || self.priority != priority
            || self.status != status;
        if !changed {
            return Ok(false);
        }
        if self.status != status {
            self.completed_at = if status == TaskStatus::Done {
                Some(Timestamp::now())
            } else {
                None
            };
        }
        self.title = title;
        self.notes = notes.to_owned();
        self.project = project;
        self.priority = priority;
        self.status = status;
        self.bump();
        Ok(true)
    }

    pub fn soft_delete(&mut self) {
        self.deleted_at = Some(Timestamp::now());
        self.bump();
    }

    fn bump(&mut self) {
        self.updated_at = Timestamp::now();
        self.version += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reviewed_common_fields_preserve_local_only_data_and_bump_once() {
        let due = Date::new(2026, 12, 5).unwrap();
        let mut task = Task::new("Original", "Personal", Priority::Low, Some(due)).unwrap();
        task.estimate_minutes = Some(35);
        task.assignee_id = Some("local".to_owned());
        let created_at = task.created_at;
        let changed = task
            .apply_reviewed_remote_common_fields(
                "Remote title",
                "Remote note",
                "SHIORI",
                Priority::High,
                TaskStatus::Done,
            )
            .unwrap();
        assert!(changed);
        assert_eq!(task.version, 2, "Five fields are one local revision");
        assert_eq!(task.title, "Remote title");
        assert_eq!(task.notes, "Remote note");
        assert_eq!(task.status, TaskStatus::Done);
        assert_eq!(task.priority, Priority::High);
        assert!(task.completed_at.is_some());
        assert_eq!(task.due_on, Some(due));
        assert_eq!(task.estimate_minutes, Some(35));
        assert_eq!(task.assignee_id.as_deref(), Some("local"));
        assert_eq!(task.created_at, created_at);
        let completed_at = task.completed_at;
        assert!(
            !task
                .apply_reviewed_remote_common_fields(
                    "Remote title",
                    "Remote note",
                    "SHIORI",
                    Priority::High,
                    TaskStatus::Done,
                )
                .unwrap()
        );
        assert_eq!(task.version, 2, "Exact replay must be a no-op");
        assert_eq!(task.completed_at, completed_at);
        task.apply_reviewed_remote_common_fields(
            "Remote title",
            "Remote note",
            "SHIORI",
            Priority::High,
            TaskStatus::Todo,
        )
        .unwrap();
        assert_eq!(task.version, 3);
        assert!(task.completed_at.is_none());
    }

    #[test]
    fn invalid_common_field_projection_changes_nothing() {
        let mut task = Task::new("Original", "Personal", Priority::Low, None).unwrap();
        let before = task.clone();
        assert_eq!(
            task.apply_reviewed_remote_common_fields(
                "",
                "notes",
                "SHIORI",
                Priority::High,
                TaskStatus::Done,
            ),
            Err(TaskError::EmptyTitle)
        );
        assert_eq!(
            task.apply_reviewed_remote_common_fields(
                "Good",
                &"n".repeat(8193),
                "SHIORI",
                Priority::High,
                TaskStatus::Done,
            ),
            Err(TaskError::SyncedNotesTooLong)
        );
        assert_eq!(task.version, before.version);
        assert_eq!(task.title, before.title);
        assert_eq!(task.notes, before.notes);
        assert_eq!(task.completed_at, before.completed_at);
    }

    #[test]
    fn rejects_empty_and_too_long_titles() {
        assert_eq!(
            Task::new(" \t ", "Inbox", Priority::Low, None).unwrap_err(),
            TaskError::EmptyTitle
        );
        assert_eq!(
            validate_title(&"x".repeat(161)),
            Err(TaskError::TitleTooLong)
        );
    }

    #[test]
    fn completion_and_reopening_clear_timestamp_and_bump_revision() {
        let mut t = Task::new("  Check something  ", " Personal ", Priority::High, None).unwrap();
        assert_eq!(t.title, "Check something");
        assert_eq!(t.project, "Personal");
        t.change_status(TaskStatus::Done);
        assert!(t.completed_at.is_some());
        t.change_status(TaskStatus::Todo);
        assert!(t.completed_at.is_none());
        assert_eq!(t.version, 3);
    }

    #[test]
    fn a_calendar_date_is_not_shifted_by_timezone_conversion() {
        let due = Date::new(2026, 11, 11).unwrap();
        assert_eq!(
            Task::new("Task", "Inbox", Priority::Low, Some(due))
                .unwrap()
                .due_on,
            Some(due)
        );
    }
}
