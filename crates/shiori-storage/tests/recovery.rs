//! Persistence and cold-backup smoke tests.
//! A live SQLite backup protocol will require separate testing once implemented.
use shiori_core::{Priority, Task, TaskStatus};
use shiori_storage::{SqliteStore, StorageError, TaskFilter};

#[test]
fn closed_database_file_copies_restore_records_and_tombstones() {
    let temp = tempfile::tempdir().unwrap();
    let original = temp.path().join("source.sqlite3");
    let snapshot = temp.path().join("backup.sqlite3");
    let mut ids = Vec::new();
    {
        let db = SqliteStore::open(&original).unwrap();
        for index in 0..48 {
            let task = Task::new(
                &format!("Record {index:03} 栞"),
                if index % 2 == 0 { "Team" } else { "Personal" },
                Priority::Medium,
                None,
            ).unwrap();
            db.insert(&task).unwrap();
            ids.push(task.id);
        }
        for id in ids.iter().take(12) {
            db.set_status(id, TaskStatus::Done).unwrap();
        }
        for id in ids.iter().take(7) {
            db.delete(id).unwrap();
        }
    }
    // This deliberately tests a *closed* SQLite DB file copy, not a live backup.
    std::fs::copy(&original, &snapshot).unwrap();
    let restored = SqliteStore::open(&snapshot).unwrap();
    assert_eq!(restored.list(TaskFilter::default()).unwrap().len(), 41);
    let all = restored.list(TaskFilter { include_deleted: true, ..Default::default() }).unwrap();
    assert_eq!(all.len(), 48);
    assert_eq!(all.iter().filter(|task| task.deleted_at.is_some()).count(), 7);
    assert_eq!(all.iter().filter(|task| task.completed_at.is_some()).count(), 12);
    assert!(matches!(restored.get(&ids[0]), Err(StorageError::NotFound)));
    assert_eq!(restored.get(&ids[30]).unwrap().title, "Record 030 栞");
}

#[test]
fn reopen_preserves_filter_results_and_does_not_duplicate_records() {
    let temp = tempfile::tempdir().unwrap();
    let path = temp.path().join("restart.sqlite3");
    let task = Task::new("Keep me", "Work", Priority::High, None).unwrap();
    {
        let db = SqliteStore::open(&path).unwrap();
        db.insert(&task).unwrap();
    }
    for _ in 0..8 {
        let db = SqliteStore::open(&path).unwrap();
        let rows = db.list(TaskFilter { project: Some("Work"), ..Default::default() }).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].id, task.id);
        assert_eq!(rows[0].version, 1);
    }
}
