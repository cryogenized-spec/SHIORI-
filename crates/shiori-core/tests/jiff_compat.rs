//! JSON compatibility with previously serialized Chrono task records.
use jiff::{Timestamp, civil::Date};
use shiori_core::{Priority, Task};

#[test]
fn pre_migration_chrono_json_deserializes_and_roundtrips_with_jiff() {
    let due = Date::new(2026, 11, 20).unwrap();
    let mut task = Task::new("Compatibility", "Inbox", Priority::Medium, Some(due)).unwrap();
    let old: Timestamp = "2026-11-17T08:23:44.250000+00:00".parse().unwrap();
    task.created_at = old;
    task.updated_at = old;
    let json = serde_json::to_string(&task).unwrap();
    let previous: Task = serde_json::from_str(&json).unwrap();
    assert_eq!(previous.due_on, Some(due));
    assert_eq!(previous.created_at, old);
    assert_eq!(previous.updated_at, old);

    let legacy = json.replace(
        "\"2026-11-17T08:23:44.25Z\"",
        "\"2026-11-17T08:23:44.250000+00:00\"",
    );
    let restored: Task = serde_json::from_str(&legacy).unwrap();
    assert_eq!(restored.created_at, old);
    assert_eq!(restored.due_on, Some(due));
    assert_eq!(restored.version, task.version);
}
