use chrono::NaiveDate;
use shiori_core::{Priority, Task, TaskStatus};
use shiori_storage::{SqliteStore, StorageError, TaskFilter};

#[test]
fn escaped_wildcards_and_sql_metacharacters_do_not_bypass_search() {
    let store = SqliteStore::in_memory().unwrap();
    let task = Task::new("Fix 100% coverage", "Core", Priority::High, None).unwrap();
    store.insert(&task).unwrap();
    assert_eq!(
        store
            .list(TaskFilter {
                search: Some("100%"),
                ..Default::default()
            })
            .unwrap()
            .len(),
        1
    );
    assert!(
        store
            .list(TaskFilter {
                search: Some("%' OR 1=1 --"),
                ..Default::default()
            })
            .unwrap()
            .is_empty()
    );
    assert!(
        store
            .list(TaskFilter {
                search: Some("_"),
                ..Default::default()
            })
            .unwrap()
            .is_empty()
    );
}

#[test]
fn filter_combinations_are_intersections_not_unions() {
    let store = SqliteStore::in_memory().unwrap();
    let due = NaiveDate::from_ymd_opt(2026, 11, 11).unwrap();
    store
        .insert(&Task::new("One", "Core", Priority::Low, Some(due)).unwrap())
        .unwrap();
    store
        .insert(&Task::new("Two", "Personal", Priority::Low, Some(due)).unwrap())
        .unwrap();
    store
        .insert(&Task::new("Three", "Core", Priority::Low, None).unwrap())
        .unwrap();
    let list = store
        .list(TaskFilter {
            project: Some("Core"),
            due_on_or_before: Some(due),
            ..Default::default()
        })
        .unwrap();
    assert_eq!(list.len(), 1);
    assert_eq!(list[0].title, "One");
}

#[test]
fn deleted_tasks_do_not_reappear_after_reopen() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("shiori.sqlite3");
    let task = Task::new("Delete me", "Inbox", Priority::Medium, None).unwrap();
    {
        let store = SqliteStore::open(&path).unwrap();
        store.insert(&task).unwrap();
        store.set_status(&task.id, TaskStatus::Done).unwrap();
        store.delete(&task.id).unwrap();
    }
    let reopened = SqliteStore::open(&path).unwrap();
    assert!(matches!(
        reopened.get(&task.id),
        Err(StorageError::NotFound)
    ));
    assert!(reopened.list(TaskFilter::default()).unwrap().is_empty());
    let deleted = reopened
        .list(TaskFilter {
            include_deleted: true,
            ..Default::default()
        })
        .unwrap();
    assert_eq!(deleted.len(), 1);
    assert_eq!(deleted[0].status, TaskStatus::Done);
    assert!(deleted[0].deleted_at.is_some());
}
