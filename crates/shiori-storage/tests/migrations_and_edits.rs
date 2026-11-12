//! Offline editing and schema-baseline migration regressions.
//! No live-backup or cross-device synchronization behaviour is claimed here.
use chrono::NaiveDate;
use rusqlite::Connection;
use shiori_core::{Priority, Task, TaskError, TaskPatch};
use shiori_storage::{SqliteStore, StorageError, TaskFilter};

#[test]
fn edits_survive_reopen_clear_dates_and_preserve_existing_identity() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("tasks.sqlite3");
    let due = NaiveDate::from_ymd_opt(2026, 11, 30).unwrap();
    let task = Task::new("Draft", "Inbox", Priority::Low, Some(due)).unwrap();
    let original_id = task.id.clone();
    let original_created = task.created_at;
    {
        let db = SqliteStore::open(&path).unwrap();
        db.insert(&task).unwrap();
        let result = db
            .edit(
                &task.id,
                TaskPatch {
                    title: Some("  Ship 栞  ".into()),
                    notes: Some("Review milestone".into()),
                    project: Some("  SHIORI  ".into()),
                    priority: Some(Priority::Urgent),
                    due_on: Some(None),
                    estimate_minutes: None,
                },
            )
            .unwrap();
        assert_eq!(result.id, original_id);
        assert_eq!(result.created_at, original_created);
        assert_eq!(result.version, 2);
        assert_eq!(result.title, "Ship 栞");
        assert_eq!(result.project, "SHIORI");
        assert_eq!(result.priority, Priority::Urgent);
        assert_eq!(result.due_on, None);
        assert_eq!(
            db.list(TaskFilter {
                search: Some("milestone"),
                ..Default::default()
            })
            .unwrap()
            .len(),
            1
        );
        let unchanged = db.edit(&task.id, TaskPatch::default()).unwrap();
        assert_eq!(unchanged.version, 2);
        let stale = db
            .edit_if_version(
                &task.id,
                1,
                TaskPatch {
                    notes: Some("Stale overwrite".into()),
                    ..Default::default()
                },
            )
            .unwrap_err();
        assert!(matches!(stale, StorageError::RevisionConflict));
        let invalid = db
            .edit(
                &task.id,
                TaskPatch {
                    title: Some("  ".into()),
                    notes: Some("must not persist".into()),
                    ..Default::default()
                },
            )
            .unwrap_err();
        assert!(matches!(
            invalid,
            StorageError::Domain(TaskError::EmptyTitle)
        ));
        assert_eq!(db.get(&task.id).unwrap().notes, "Review milestone");
    }
    let reopened = SqliteStore::open(&path).unwrap();
    let persisted = reopened.get(&task.id).unwrap();
    assert_eq!(persisted.version, 2);
    assert_eq!(persisted.title, "Ship 栞");
    assert_eq!(persisted.notes, "Review milestone");
    assert_eq!(persisted.project, "SHIORI");
    assert_eq!(persisted.due_on, None);
    assert_eq!(persisted.created_at, original_created);
}

#[test]
fn unversioned_legacy_database_upgrades_without_dropping_tombstones() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("legacy.sqlite3");
    let active = Task::new("Active", "Inbox", Priority::Medium, None).unwrap();
    let deleted = Task::new("Deleted", "Inbox", Priority::Medium, None).unwrap();
    {
        let db = SqliteStore::open(&path).unwrap();
        db.insert(&active).unwrap();
        db.insert(&deleted).unwrap();
        db.delete(&deleted.id).unwrap();
    }
    // Recreate the precise pre-versioning state: the same schema and records
    // were already present, but SQLite user_version was still zero.
    Connection::open(&path)
        .unwrap()
        .execute_batch("PRAGMA user_version = 0;")
        .unwrap();
    for _ in 0..2 {
        let db = SqliteStore::open(&path).unwrap();
        assert_eq!(db.get(&active.id).unwrap().version, 1);
        assert!(matches!(db.get(&deleted.id), Err(StorageError::NotFound)));
        let all = db
            .list(TaskFilter {
                include_deleted: true,
                ..Default::default()
            })
            .unwrap();
        assert_eq!(all.len(), 2);
        assert_eq!(
            all.iter().filter(|task| task.deleted_at.is_some()).count(),
            1
        );
    }
    let conn = Connection::open(&path).unwrap();
    let version: i64 = conn
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .unwrap();
    assert_eq!(version, 2);
}

#[test]
fn refuses_unknown_newer_schema_without_modifying_database() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("future.sqlite3");
    let db = Connection::open(&path).unwrap();
    db.execute_batch("PRAGMA user_version = 42;").unwrap();
    drop(db);
    assert!(matches!(
        SqliteStore::open(&path),
        Err(StorageError::UnsupportedSchemaVersion {
            found: 42,
            supported: 2
        })
    ));
    let db = Connection::open(&path).unwrap();
    let version: i64 = db
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .unwrap();
    assert_eq!(version, 42);
    assert_eq!(
        db.query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='tasks'",
            [],
            |row| row.get::<_, i64>(0)
        )
        .unwrap(),
        0
    );
}

#[test]
fn incompatible_unversioned_schema_rolls_back_cleanly() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("unexpected.sqlite3");
    let db = Connection::open(&path).unwrap();
    db.execute_batch(
        "CREATE TABLE tasks (
            id TEXT PRIMARY KEY, project TEXT, deleted_at TEXT,
            due_on TEXT, status TEXT, created_at TEXT
        );",
    )
    .unwrap();
    drop(db);
    assert!(matches!(
        SqliteStore::open(&path),
        Err(StorageError::IncompatibleLegacySchema)
    ));
    let db = Connection::open(&path).unwrap();
    let version: i64 = db
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .unwrap();
    assert_eq!(version, 0);
    let indexes: i64 = db
        .query_row(
            "SELECT count(*) FROM sqlite_master WHERE type='index' AND name='idx_tasks_active_due'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(indexes, 0);
}

#[test]
fn deleted_task_cannot_be_edited_or_resurrected() {
    let db = SqliteStore::in_memory().unwrap();
    let task = Task::new("Delete", "Inbox", Priority::Low, None).unwrap();
    db.insert(&task).unwrap();
    db.delete(&task.id).unwrap();
    assert!(matches!(
        db.edit(
            &task.id,
            TaskPatch {
                title: Some("Resurrect".into()),
                ..Default::default()
            }
        ),
        Err(StorageError::NotFound)
    ));
    assert_eq!(
        db.list(TaskFilter {
            include_deleted: true,
            ..Default::default()
        })
        .unwrap()
        .len(),
        1
    );
}
