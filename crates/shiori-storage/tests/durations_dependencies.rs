//! M2/M3: tasks keep their own estimates and safe prerequisite edges.
use rusqlite::{Connection, params};
use shiori_core::{Priority, Task, TaskError, TaskPatch, TaskStatus};
use shiori_storage::{SqliteStore, StorageError, TaskFilter};

#[test]
fn estimate_edits_survive_reopen_and_reject_invalid_mutations() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("estimates.db");
    let task = Task::new("Plan SHIORI", "Core", Priority::High, None).unwrap();
    {
        let db = SqliteStore::open(&path).unwrap();
        db.insert(&task).unwrap();
        let saved = db
            .edit(
                &task.id,
                TaskPatch {
                    estimate_minutes: Some(Some(80)),
                    ..Default::default()
                },
            )
            .unwrap();
        assert_eq!(saved.estimate_minutes, Some(80));
        assert_eq!(saved.version, 2);
        assert!(matches!(
            db.edit(
                &task.id,
                TaskPatch {
                    title: Some("Accidental".into()),
                    estimate_minutes: Some(Some(-3)),
                    ..Default::default()
                },
            ),
            Err(StorageError::Domain(TaskError::InvalidEstimate))
        ));
        assert_eq!(db.get(&task.id).unwrap().title, "Plan SHIORI");
    }
    let db = SqliteStore::open(&path).unwrap();
    assert_eq!(db.get(&task.id).unwrap().estimate_minutes, Some(80));
    db.edit(
        &task.id,
        TaskPatch {
            estimate_minutes: Some(None),
            ..Default::default()
        },
    )
    .unwrap();
    assert_eq!(db.get(&task.id).unwrap().estimate_minutes, None);
}

#[test]
fn dependencies_validate_full_graph_atomically_and_preserve_tombstones() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("edges.db");
    let a = Task::new("A", "Core", Priority::Low, None).unwrap();
    let b = Task::new("B", "Core", Priority::Low, None).unwrap();
    let c = Task::new("C", "Core", Priority::Low, None).unwrap();
    {
        let mut db = SqliteStore::open(&path).unwrap();
        for task in [&a, &b, &c] {
            db.insert(task).unwrap();
        }
        db.set_dependencies(&b.id, std::slice::from_ref(&a.id))
            .unwrap();
        db.set_dependencies(&c.id, std::slice::from_ref(&b.id))
            .unwrap();
        assert_eq!(db.get_dependencies(&c.id).unwrap(), vec![b.id.clone()]);
        assert_eq!(db.get(&c.id).unwrap().version, 2);
        assert!(matches!(
            db.set_dependencies(&a.id, std::slice::from_ref(&c.id)),
            Err(StorageError::DependencyCycle)
        ));
        assert!(matches!(
            db.set_dependencies(&a.id, std::slice::from_ref(&a.id)),
            Err(StorageError::DependencyCycle)
        ));
        assert!(matches!(
            db.set_dependencies(&a.id, &[b.id.clone(), b.id.clone()]),
            Err(StorageError::DuplicateDependency)
        ));
        assert!(matches!(
            db.set_dependencies(&a.id, &["unknown".into()]),
            Err(StorageError::MissingDependency(_))
        ));
        assert!(db.get_dependencies(&a.id).unwrap().is_empty());
        assert_eq!(db.get_dependencies(&c.id).unwrap(), vec![b.id.clone()]);
        assert_eq!(db.get(&a.id).unwrap().version, 1);
        db.set_dependencies(&c.id, std::slice::from_ref(&b.id))
            .unwrap();
        assert_eq!(db.get(&c.id).unwrap().version, 2);
        db.delete(&a.id).unwrap();
        assert!(matches!(
            db.set_dependencies(&b.id, std::slice::from_ref(&a.id)),
            Err(StorageError::MissingDependency(_))
        ));
    }
    let db = SqliteStore::open(&path).unwrap();
    assert_eq!(db.get_dependencies(&c.id).unwrap(), vec![b.id.clone()]);
    assert!(matches!(db.get(&a.id), Err(StorageError::NotFound)));
    assert_eq!(
        db.list(TaskFilter {
            include_deleted: true,
            ..Default::default()
        })
        .unwrap()
        .len(),
        3
    );
}

#[test]
fn version_one_database_upgrades_without_losing_existing_or_deleted_tasks() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("legacy-v1.db");
    let active = Task::new("Legacy active", "Core", Priority::High, None).unwrap();
    let mut deleted = Task::new("Legacy deleted", "Core", Priority::Low, None).unwrap();
    deleted.soft_delete();
    {
        let db = Connection::open(&path).unwrap();
        db.execute_batch(
            "CREATE TABLE tasks (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL DEFAULT '',
                project TEXT NOT NULL,
                priority TEXT NOT NULL CHECK(priority IN ('low','medium','high','urgent')),
                status TEXT NOT NULL CHECK(status IN ('todo','in_progress','done')),
                due_on TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                completed_at TEXT, version INTEGER NOT NULL CHECK(version > 0),
                deleted_at TEXT
            );
            PRAGMA user_version = 1;",
        )
        .unwrap();
        for task in [&active, &deleted] {
            db.execute(
                "INSERT INTO tasks(id,title,notes,project,priority,status,due_on,created_at,updated_at,completed_at,version,deleted_at)
                 VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12)",
                params![
                    task.id, task.title, task.notes, task.project,
                    task.priority.as_str(), task.status.as_str(),
                    task.due_on.map(|day| day.to_string()),
                    task.created_at.to_rfc3339(), task.updated_at.to_rfc3339(),
                    task.completed_at.map(|at| at.to_rfc3339()),
                    task.version, task.deleted_at.map(|at| at.to_rfc3339())
                ],
            )
            .unwrap();
        }
    }
    let db = SqliteStore::open(&path).unwrap();
    assert_eq!(db.get(&active.id).unwrap().estimate_minutes, None);
    assert_eq!(db.get(&active.id).unwrap().version, 1);
    assert!(db.get_dependencies(&active.id).unwrap().is_empty());
    assert!(matches!(db.get(&deleted.id), Err(StorageError::NotFound)));
    assert_eq!(
        db.list(TaskFilter {
            include_deleted: true,
            ..Default::default()
        })
        .unwrap()
        .len(),
        2
    );
    let reopened = SqliteStore::open(&path).unwrap();
    assert_eq!(reopened.get(&active.id).unwrap().version, 1);
    let v: i64 = Connection::open(&path)
        .unwrap()
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .unwrap();
    assert_eq!(v, 3);
}

#[test]
fn done_predecessor_is_still_addressable() {
    let mut store = SqliteStore::in_memory().unwrap();
    let before = Task::new("Review", "Core", Priority::Low, None).unwrap();
    let after = Task::new("Publish", "Core", Priority::High, None).unwrap();
    store.insert(&before).unwrap();
    store.insert(&after).unwrap();
    store.set_status(&before.id, TaskStatus::Done).unwrap();
    store
        .set_dependencies(&after.id, std::slice::from_ref(&before.id))
        .unwrap();
    assert_eq!(store.get_dependencies(&after.id).unwrap(), vec![before.id]);
}
