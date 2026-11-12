use shiori_core::{Priority, Task, TaskError, TaskPatch, TaskStatus};
use shiori_storage::{SqliteStore, StorageError};

#[test]
fn local_assignments_are_indexed_and_report_blockers() {
    let mut store = SqliteStore::in_memory().unwrap();
    let mut prepare = Task::new("Prepare", "Work", Priority::Low, None).unwrap();
    prepare.assignee_id = Some("local".into());
    let mut publish = Task::new("Publish", "Work", Priority::Urgent, None).unwrap();
    publish.assignee_id = Some("local".into());
    let mut other = Task::new("Not mine", "Work", Priority::High, None).unwrap();
    other.assignee_id = Some("another-user".into());
    let unassigned = Task::new("Unassigned", "Work", Priority::High, None).unwrap();
    for task in [&prepare, &publish, &other, &unassigned] {
        store.insert(task).unwrap();
    }
    store
        .set_dependencies(&publish.id, std::slice::from_ref(&prepare.id))
        .unwrap();
    let assignments = store.assigned_attention("local").unwrap();
    assert_eq!(assignments.len(), 2);
    assert!(assignments.iter().any(|(task, blocked)| {
        task.id == publish.id && *blocked
    }));
    assert!(assignments.iter().any(|(task, blocked)| {
        task.id == prepare.id && !*blocked
    }));
    store.set_status(&prepare.id, TaskStatus::Done).unwrap();
    let assignments = store.assigned_attention("local").unwrap();
    assert_eq!(assignments.len(), 1);
    assert_eq!(assignments[0].0.id, publish.id);
    assert!(!assignments[0].1);
    store
        .edit(
            &publish.id,
            TaskPatch {
                assignee_id: Some(None),
                ..Default::default()
            },
        )
        .unwrap();
    assert!(store.assigned_attention("local").unwrap().is_empty());
    assert!(store.assigned_attention("another-user").is_ok());
}

#[test]
fn invalid_identity_and_deleted_predecessor_remain_blocked() {
    let mut store = SqliteStore::in_memory().unwrap();
    let mut prerequisite = Task::new("Prerequisite", "Work", Priority::Low, None).unwrap();
    prerequisite.assignee_id = Some("local".into());
    let mut current = Task::new("Current", "Work", Priority::High, None).unwrap();
    current.assignee_id = Some("local".into());
    store.insert(&prerequisite).unwrap();
    store.insert(&current).unwrap();
    store
        .set_dependencies(&current.id, std::slice::from_ref(&prerequisite.id))
        .unwrap();
    store.delete(&prerequisite.id).unwrap();
    let attention = store.assigned_attention("local").unwrap();
    assert_eq!(attention.len(), 1);
    assert!(attention[0].1);
    assert!(matches!(
        store.edit(
            &current.id,
            TaskPatch {
                assignee_id: Some(Some("bad user!".into())),
                title: Some("not committed".into()),
                ..Default::default()
            }
        ),
        Err(StorageError::Domain(TaskError::InvalidAssignee))
    ));
    assert_eq!(store.get(&current.id).unwrap().title, "Current");
}
