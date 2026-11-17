//! SQLite v3 compatibility checks for pre-Jiff saved tasks.
use jiff::{Timestamp, civil::Date};
use rusqlite::{Connection, params};
use shiori_core::{Priority, Task, TaskStatus, utc_rfc3339};
use shiori_storage::SqliteStore;

#[test]
fn pre_migration_rfc3339_and_calendar_date_survive_roundtrip() {
    let dir = tempfile::tempdir().unwrap();
    let db_path = dir.path().join("pre-jiff-v3.sqlite3");
    let store = SqliteStore::open(&db_path).unwrap();
    let due = Date::new(2024, 2, 29).unwrap();
    let task = Task::new("Legacy saved date", "Offline", Priority::High, Some(due)).unwrap();
    store.insert(&task).unwrap();

    // Chrono historically emitted +00:00 in SQLite; accept both this and
    // positive-offset timestamps without shifting a calendar-only due date.
    let db = Connection::open(&db_path).unwrap();
    db.execute(
        "UPDATE tasks SET created_at=?1, updated_at=?2 WHERE id=?3",
        params![
            "2024-02-28T23:58:59.123456+00:00",
            "2024-02-29T01:58:59.123456+02:00",
            task.id
        ],
    )
    .unwrap();
    let old = store.get(&task.id).unwrap();
    assert_eq!(old.due_on, Some(due));
    let instant: Timestamp = "2024-02-28T23:58:59.123456Z".parse().unwrap();
    assert_eq!(old.created_at, instant);
    assert_eq!(old.updated_at, instant);
    assert_eq!(utc_rfc3339(instant), "2024-02-28T23:58:59.123456+00:00");

    let updated = store.set_status(&task.id, TaskStatus::Done).unwrap();
    assert_eq!(updated.due_on, Some(due));
    assert_eq!(updated.created_at, instant);
    let timestamp: String = db
        .query_row(
            "SELECT updated_at FROM tasks WHERE id=?1",
            params![task.id],
            |row| row.get(0),
        )
        .unwrap();
    assert!(
        timestamp.ends_with("+00:00"),
        "legacy UTC spelling changed: {timestamp}"
    );
}
