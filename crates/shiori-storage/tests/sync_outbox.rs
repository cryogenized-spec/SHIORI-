//! The sync journal must never alter canonical SQLite task records.
use shiori_core::{Priority, Task, TaskPatch, TaskStatus};
use shiori_storage::{SqliteStore, SyncJournal, SyncJournalError};
use tempfile::tempdir;

#[test]
fn journal_stages_lossless_snapshots_retries_and_tombstones_without_upload() {
    let folder = tempdir().unwrap();
    let primary = folder.path().join("tasks.sqlite3");
    let outbox = folder.path().join("tasks.sync.sqlite3");
    let native = SqliteStore::open(&primary).unwrap();
    let mut task = Task::new("Private customer", "Repairs", Priority::High, None).unwrap();
    task.notes = "Sensitive data stays local, never on a report".to_owned();
    native.insert(&task).unwrap();
    let mut journal = SyncJournal::open(&outbox).unwrap();
    let device_id = journal.device_id().to_owned();
    let (first, inserted) = journal.stage(&task, &[]).unwrap();
    assert!(inserted);
    assert!(first.event_id.contains(&device_id));
    assert_eq!(first.local_version, 1);
    assert_eq!(first.state, "pending");
    assert!(!format!("{first:?}").contains("Sensitive data"));
    assert_eq!(journal.list(50).unwrap().len(), 1);
    let (same, inserted_again) = journal.stage(&task, &[]).unwrap();
    assert!(!inserted_again);
    assert_eq!(same.event_id, first.event_id);
    let payload = journal.staged_envelope(&first.event_id).unwrap();
    assert_eq!(payload.task.notes, task.notes);
    assert_eq!(payload.task.id, task.id);
    assert_eq!(payload.origin_device_id, device_id);
    assert_eq!(payload.workspace_id, "personal");
    assert_eq!(native.get(&task.id).unwrap().version, 1);
    drop(journal);

    // Restarting never generates a new device ID or loses the queue.
    let mut journal = SyncJournal::open(&outbox).unwrap();
    assert_eq!(journal.device_id(), device_id);
    assert_eq!(journal.list(50).unwrap()[0].event_id, first.event_id);
    let edited = native
        .edit_if_version(
            &task.id,
            1,
            TaskPatch {
                title: Some("Private customer - revised".to_owned()),
                ..TaskPatch::default()
            },
        )
        .unwrap();
    let (new_event, changed) = journal.stage(&edited, &[]).unwrap();
    assert!(changed);
    assert_ne!(first.event_id, new_event.event_id);
    assert_eq!(new_event.local_version, 2);
    assert_eq!(journal.list(50).unwrap().len(), 2);

    // Receipt mismatches cannot cause an event to be acknowledged.
    assert!(matches!(
        journal.acknowledge(&first.event_id, "cloud-id", 1, "wrong-task-id", 1),
        Err(SyncJournalError::ReceiptMismatch)
    ));
    assert!(
        journal
            .acknowledge(&first.event_id, "cloud-id", 1, &task.id, 1)
            .unwrap()
    );
    assert!(
        !journal
            .acknowledge(&first.event_id, "cloud-id", 1, &task.id, 1)
            .unwrap()
    );
    assert!(matches!(
        journal.acknowledge(&first.event_id, "different-cloud-id", 1, &task.id, 1),
        Err(SyncJournalError::ReceiptMismatch)
    ));
    assert_eq!(journal.list(50).unwrap()[0].state, "acknowledged");
    assert!(journal.staged_envelope(&first.event_id).is_err());
    assert_eq!(journal.list(50).unwrap()[1].state, "pending");
    journal.mark_conflict(&new_event.event_id).unwrap();
    assert_eq!(journal.list(50).unwrap()[1].state, "conflict");
    assert_eq!(native.get(&task.id).unwrap().version, 2);

    // Deletion preserves the local record and stages a tombstone, not a purge.
    native.delete_if_version(&task.id, 2).unwrap();
    assert!(native.get(&task.id).is_err());
    let tombstone = native.get_including_deleted(&task.id).unwrap();
    assert!(tombstone.deleted_at.is_some());
    assert_eq!(tombstone.version, 3);
    let (delete_event, added) = journal.stage(&tombstone, &[]).unwrap();
    assert!(added);
    assert!(
        journal
            .staged_envelope(&delete_event.event_id)
            .unwrap()
            .task
            .deleted_at
            .is_some()
    );
    assert_eq!(native.get_including_deleted(&task.id).unwrap().version, 3);
}

#[test]
fn same_revision_with_different_edges_fails_instead_of_last_write_wins() {
    let tmp = tempdir().unwrap();
    let mut journal = SyncJournal::open(tmp.path().join("journal.db")).unwrap();
    let task = Task::new("Alpha", "Inbox", Priority::Low, None).unwrap();
    journal.stage(&task, &["task-1".to_owned()]).unwrap();
    let error = journal.stage(&task, &["task-2".to_owned()]).unwrap_err();
    assert!(matches!(error, SyncJournalError::SnapshotConflict));
    let same_edge = ["task-1".to_owned(), "task-1".to_owned()];
    assert!(matches!(
        journal.stage(&task, &same_edge),
        Err(SyncJournalError::InvalidSnapshot)
    ));
    assert!(matches!(
        journal.stage(&task, &[task.id.clone()]),
        Err(SyncJournalError::InvalidSnapshot)
    ));
}

#[test]
fn unknown_schema_and_existing_canonical_database_are_rejected() {
    let tmp = tempdir().unwrap();
    let primary = tmp.path().join("primary.db");
    let native = SqliteStore::open(&primary).unwrap();
    let task = Task::new("Keep me", "Inbox", Priority::Medium, None).unwrap();
    native.insert(&task).unwrap();
    assert!(matches!(
        SyncJournal::open(&primary),
        Err(SyncJournalError::UnsupportedSchema(3))
    ));
    assert_eq!(native.get(&task.id).unwrap().title, "Keep me");
    let journal_file = tmp.path().join("future.db");
    let db = rusqlite::Connection::open(&journal_file).unwrap();
    db.pragma_update(None, "user_version", 8_i64).unwrap();
    drop(db);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&journal_file, std::fs::Permissions::from_mode(0o600)).unwrap();
    }
    assert!(matches!(
        SyncJournal::open(&journal_file),
        Err(SyncJournalError::UnsupportedSchema(8))
    ));
    // No direct access to future version; never downgrade it.
    let db = rusqlite::Connection::open(&journal_file).unwrap();
    assert_eq!(
        db.pragma_query_value(None, "user_version", |r| r.get::<_, i64>(0))
            .unwrap(),
        8
    );
}

#[cfg(unix)]
#[test]
fn journal_is_private_and_rejects_symlink_or_world_readable_files() {
    use std::os::unix::fs::{PermissionsExt, symlink};
    let tmp = tempdir().unwrap();
    let path = tmp.path().join("private.db");
    let _journal = SyncJournal::open(&path).unwrap();
    let mode = std::fs::metadata(&path).unwrap().permissions().mode();
    assert_eq!(mode & 0o077, 0);
    let link = tmp.path().join("link.db");
    symlink(&path, &link).unwrap();
    assert!(matches!(
        SyncJournal::open(&link),
        Err(SyncJournalError::UnsafeJournalFile)
    ));
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o644)).unwrap();
    assert!(matches!(
        SyncJournal::open(&path),
        Err(SyncJournalError::UnsafeJournalFile)
    ));
}

#[test]
fn stage_does_not_change_status_or_dependencies() {
    let tmp = tempdir().unwrap();
    let native = SqliteStore::open(tmp.path().join("primary.sqlite3")).unwrap();
    let task = Task::new("Stay open", "Inbox", Priority::Medium, None).unwrap();
    native.insert(&task).unwrap();
    let task = native.set_status(&task.id, TaskStatus::InProgress).unwrap();
    let mut journal = SyncJournal::open(tmp.path().join("outbox.sqlite3")).unwrap();
    journal.stage(&task, &[]).unwrap();
    assert_eq!(native.get(&task.id).unwrap().status, TaskStatus::InProgress);
    assert_eq!(native.get(&task.id).unwrap().version, 2);
}
