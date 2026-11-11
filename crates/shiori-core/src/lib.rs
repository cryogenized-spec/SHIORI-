//! SHIORI's platform-independent task model.
//! No filesystem, database, MCP, HTTP or UI dependencies belong here.

use chrono::{DateTime, NaiveDate, Utc};
use serde::{Deserialize, Serialize};
use std::str::FromStr;
use thiserror::Error;
use uuid::Uuid;

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
    #[error("invalid priority")]
    InvalidPriority,
    #[error("invalid task status")]
    InvalidStatus,
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
    pub due_on: Option<NaiveDate>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub completed_at: Option<DateTime<Utc>>,
    /// Incremented on every mutation; base for future conflict detection.
    pub version: i64,
    /// Tombstones preserve deletions for eventual synchronization.
    pub deleted_at: Option<DateTime<Utc>>,
}

impl Task {
    pub fn new(
        title: &str,
        project: &str,
        priority: Priority,
        due_on: Option<NaiveDate>,
    ) -> Result<Self, TaskError> {
        let title = validate_title(title)?;
        let project = project.trim();
        if project.is_empty() {
            return Err(TaskError::EmptyProject);
        }
        let now = Utc::now();
        Ok(Self {
            id: Uuid::now_v7().to_string(),
            title,
            notes: String::new(),
            project: project.to_owned(),
            priority,
            status: TaskStatus::Todo,
            due_on,
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
            Some(Utc::now())
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

    pub fn soft_delete(&mut self) {
        self.deleted_at = Some(Utc::now());
        self.bump();
    }

    fn bump(&mut self) {
        self.updated_at = Utc::now();
        self.version += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

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
        let due = NaiveDate::from_ymd_opt(2026, 11, 11).unwrap();
        assert_eq!(
            Task::new("Task", "Inbox", Priority::Low, Some(due))
                .unwrap()
                .due_on,
            Some(due)
        );
    }
}
