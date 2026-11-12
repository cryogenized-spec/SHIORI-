use chrono::NaiveDate;
use shiori_core::{Priority, Task, TaskError, TaskPatch};

#[test]
fn patch_validates_before_mutating_and_does_not_bump_noop() {
    let mut task = Task::new("Original", "Inbox", Priority::Medium, None).unwrap();
    let original = task.clone();
    let invalid = task.apply_patch(TaskPatch {
        notes: Some("Should not stick".into()),
        title: Some("   ".into()),
        ..Default::default()
    });
    assert_eq!(invalid, Err(TaskError::EmptyTitle));
    assert_eq!(task.title, original.title);
    assert_eq!(task.notes, original.notes);
    assert_eq!(task.version, original.version);
    assert!(!task.apply_patch(TaskPatch::default()).unwrap());
    assert_eq!(task.version, original.version);
    let due = NaiveDate::from_ymd_opt(2026, 11, 20).unwrap();
    assert!(task.apply_patch(TaskPatch {
        due_on: Some(Some(due)),
        project: Some("  Work  ".into()),
        ..Default::default()
    }).unwrap());
    assert_eq!(task.project, "Work");
    assert_eq!(task.due_on, Some(due));
    assert_eq!(task.version, 2);
    assert!(task.apply_patch(TaskPatch {
        due_on: Some(None),
        ..Default::default()
    }).unwrap());
    assert_eq!(task.due_on, None);
    assert_eq!(task.version, 3);
}
