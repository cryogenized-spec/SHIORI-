use chrono::NaiveDate;
use shiori_core::{Priority, Task, TaskError, TaskStatus, validate_title};

#[test]
fn title_constraints_count_unicode_scalars_not_bytes() {
    assert_eq!(
        validate_title(&"栞".repeat(160)).unwrap().chars().count(),
        160
    );
    assert_eq!(
        validate_title(&"栞".repeat(161)),
        Err(TaskError::TitleTooLong)
    );
    assert_eq!(validate_title("  \n "), Err(TaskError::EmptyTitle));
}

#[test]
fn completion_is_reversible_and_revisions_are_monotonic() {
    let mut task = Task::new("Schedule a release", "Core", Priority::Urgent, None).unwrap();
    let original = task.version;
    for cycle in 0..30 {
        task.change_status(TaskStatus::Done);
        assert!(
            task.completed_at.is_some(),
            "missing completion on cycle {cycle}"
        );
        task.change_status(TaskStatus::Todo);
        assert!(
            task.completed_at.is_none(),
            "stale completion on cycle {cycle}"
        );
    }
    assert_eq!(task.version, original + 60);
}

#[test]
fn due_date_is_preserved_as_a_calendar_day() {
    for (year, month, day) in [(2024, 2, 29), (2026, 11, 11), (2030, 12, 31)] {
        let day = NaiveDate::from_ymd_opt(year, month, day).unwrap();
        let task = Task::new("Check date", "Inbox", Priority::Low, Some(day)).unwrap();
        assert_eq!(task.due_on, Some(day));
    }
}

#[test]
fn deleted_task_retains_identity_and_increments_version() {
    let mut task = Task::new("Remove", "Inbox", Priority::Low, None).unwrap();
    let id = task.id.clone();
    task.soft_delete();
    assert_eq!(task.id, id);
    assert!(task.deleted_at.is_some());
    assert_eq!(task.version, 2);
}
