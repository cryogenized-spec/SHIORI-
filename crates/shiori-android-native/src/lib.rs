//! Non-destructive Android snapshot vault, stored in app-private SQLite.
//!
//! This is a transitional persistence layer. It deliberately does NOT import
//! the WebView task format into canonical shiori-storage task records yet.
//! Never silently overwrite the last native snapshot at Activity startup.
use chrono::NaiveDate;
use jni::{
    JNIEnv,
    objects::{JObject, JString},
    sys::{JNI_FALSE, JNI_TRUE, jboolean, jstring},
};
use rusqlite::{Connection, OptionalExtension, params};
use serde_json::Value;
use std::{collections::HashSet, path::Path, time::Duration};

const MAX_SNAPSHOT_BYTES: usize = 2_000_000;
const FORMAT: &str = "shiori-android-local-v1";

fn validate_snapshot(raw: &str) -> Result<(), &'static str> {
    if raw.len() > MAX_SNAPSHOT_BYTES {
        return Err("snapshot exceeds limit");
    }
    let data: Value = serde_json::from_str(raw).map_err(|_| "invalid JSON")?;
    let root = data.as_object().ok_or("expected backup object")?;
    if root.get("format").and_then(Value::as_str) != Some(FORMAT) {
        return Err("unrecognized backup format");
    }
    let tasks = root
        .get("tasks")
        .and_then(Value::as_array)
        .ok_or("missing tasks array")?;
    let views = root
        .get("saved_views")
        .and_then(Value::as_array)
        .ok_or("missing saved views")?;
    if tasks.len() > 5000 || views.len() > 30 {
        return Err("snapshot count exceeds limit");
    }
    let mut ids = HashSet::new();
    for task in tasks {
        let task = task.as_object().ok_or("invalid task")?;
        let field = |name| task.get(name).and_then(Value::as_str);
        let id = field("id").ok_or("task ID missing")?;
        let title = field("title").ok_or("title missing")?;
        let project = field("project").ok_or("project missing")?;
        let notes = field("description").unwrap_or("");
        let priority = field("priority").ok_or("priority missing")?;
        let status = field("status").ok_or("status missing")?;
        let due = field("due").unwrap_or("");
        if id.is_empty()
            || id.len() > 128
            || !ids.insert(id)
            || title.trim().is_empty()
            || title.chars().count() > 120
            || project.trim().is_empty()
            || project.chars().count() > 160
            || notes.chars().count() > 6000
            || !["low", "medium", "high", "urgent"].contains(&priority)
            || !["todo", "progress", "done"].contains(&status)
        {
            return Err("invalid task fields");
        }
        if !due.is_empty() && NaiveDate::parse_from_str(due, "%Y-%m-%d").is_err() {
            return Err("invalid calendar date");
        }
        if let Some(minutes) = task.get("mins").filter(|v| !v.is_null()) {
            if !matches!(minutes.as_i64(), Some(1..=1440)) {
                return Err("invalid effort");
            }
        }
        if let Some(assignee) = task.get("assigneeId").filter(|v| !v.is_null()) {
            let id = assignee.as_str().ok_or("invalid assignee")?;
            if id.is_empty()
                || id.len() > 64
                || !id
                    .bytes()
                    .all(|c| c.is_ascii_alphanumeric() || b"-_.:".contains(&c))
            {
                return Err("invalid assignee ID");
            }
        }
        if let Some(tags) = task.get("tags") {
            let tags = tags.as_array().ok_or("invalid tags")?;
            if tags.len() > 16 || tags.iter().any(|t| t.as_str().is_none_or(|s| s.len() > 50)) {
                return Err("invalid tags");
            }
        }
    }
    for view in views {
        let v = view.as_object().ok_or("invalid saved view")?;
        let field = |name| v.get(name).and_then(Value::as_str);
        let name = field("name").ok_or("missing view name")?;
        if name.trim().is_empty()
            || name.len() > 40
            || !matches!(
                field("view"),
                Some("today" | "attention" | "inbox" | "board")
            )
            || !matches!(
                field("filter"),
                Some("all" | "urgent" | "high" | "medium" | "low")
            )
            || !matches!(field("sort"), Some("focus" | "fifo" | "due" | "priority"))
            || field("query").is_none_or(|q| q.len() > 250)
        {
            return Err("invalid view");
        }
    }
    if !matches!(
        root.get("sort").and_then(Value::as_str),
        Some("focus" | "fifo" | "due" | "priority")
    ) {
        return Err("invalid ordering");
    }
    Ok(())
}

/// One SQLite snapshot with transactional replacement. Never delete the
/// previous snapshot on malformed input or an interrupted write.
pub fn store_snapshot(db_path: &Path, payload: &str) -> Result<(), Box<dyn std::error::Error>> {
    validate_snapshot(payload)?;
    let mut db = Connection::open(db_path)?;
    db.busy_timeout(Duration::from_secs(3))?;
    let tx = db.transaction()?;
    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS android_snapshot (
             id INTEGER PRIMARY KEY CHECK(id = 1),
             payload TEXT NOT NULL,
             stored_at TEXT NOT NULL
         );",
    )?;
    tx.execute(
        "INSERT INTO android_snapshot(id, payload, stored_at)
         VALUES (1, ?1, datetime('now'))
         ON CONFLICT(id) DO UPDATE SET
             payload=excluded.payload, stored_at=excluded.stored_at",
        params![payload],
    )?;
    tx.commit()?;
    Ok(())
}

pub fn load_snapshot(db_path: &Path) -> Result<Option<String>, Box<dyn std::error::Error>> {
    let db = Connection::open(db_path)?;
    db.busy_timeout(Duration::from_secs(3))?;
    db.execute_batch(
        "CREATE TABLE IF NOT EXISTS android_snapshot (
             id INTEGER PRIMARY KEY CHECK(id = 1),
             payload TEXT NOT NULL,
             stored_at TEXT NOT NULL
         );",
    )?;
    Ok(db
        .query_row(
            "SELECT payload FROM android_snapshot WHERE id = 1",
            [],
            |row| row.get::<_, String>(0),
        )
        .optional()?)
}

// JNI instance methods live on the Kotlin singleton NativeVault.
// Keep Java-facing operations limited to private-path snapshot read/write;
// the only caller is the app's Kotlin Activity. No JS JNI object is exposed.
#[unsafe(no_mangle)]
pub extern "system" fn Java_dev_cryogenized_shiori_NativeVault_loadSnapshot(
    mut env: JNIEnv,
    _object: JObject,
    path: JString,
) -> jstring {
    let Ok(path) = env.get_string(&path) else {
        return std::ptr::null_mut();
    };
    let path = String::from(path);
    let Some(snapshot) = load_snapshot(Path::new(&path)).ok().flatten() else {
        return std::ptr::null_mut();
    };
    env.new_string(snapshot)
        .map_or(std::ptr::null_mut(), |value| value.into_raw())
}

#[unsafe(no_mangle)]
pub extern "system" fn Java_dev_cryogenized_shiori_NativeVault_storeSnapshot(
    mut env: JNIEnv,
    _object: JObject,
    path: JString,
    payload: JString,
) -> jboolean {
    let Ok(path) = env.get_string(&path) else {
        return JNI_FALSE;
    };
    let path = String::from(path);
    let Ok(payload) = env.get_string(&payload) else {
        return JNI_FALSE;
    };
    let payload = String::from(payload);
    if store_snapshot(Path::new(&path), &payload).is_ok() {
        JNI_TRUE
    } else {
        JNI_FALSE
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample() -> String {
        serde_json::json!({
            "format":FORMAT,
            "exported_at":"2026-11-12T12:00:00Z",
            "tasks":[{"id":"task-01","title":"Check 栞","project":"Core",
                "description":"Unicode café\\nsecond line","priority":"high",
                "status":"todo","due":"2026-11-12","mins":30,"tags":[]}],
            "saved_views":[],
            "sort":"fifo"
        })
        .to_string()
    }

    #[test]
    fn native_vault_persists_after_reopen_and_rejects_bad_updates() {
        let db = std::env::temp_dir().join(format!(
            "shiori-vault-test-{}-{}.db",
            std::process::id(),
            chrono::Utc::now().timestamp_nanos_opt().unwrap()
        ));
        assert!(load_snapshot(&db).unwrap().is_none());
        let payload = sample();
        store_snapshot(&db, &payload).unwrap();
        assert_eq!(load_snapshot(&db).unwrap(), Some(payload.clone()));
        assert!(store_snapshot(&db, "not JSON").is_err());
        assert_eq!(load_snapshot(&db).unwrap(), Some(payload.clone()));
        let mut bad: Value = serde_json::from_str(&payload).unwrap();
        bad["tasks"][0]["id"] = Value::String(String::new());
        assert!(store_snapshot(&db, &bad.to_string()).is_err());
        assert_eq!(load_snapshot(&db).unwrap(), Some(payload));
        std::fs::remove_file(db).unwrap();
    }

    #[test]
    fn duplicate_ids_invalid_dates_and_excessive_sizes_fail_closed() {
        let mut payload: Value = serde_json::from_str(&sample()).unwrap();
        payload["tasks"][0]["due"] = Value::String("2026-02-30".into());
        assert!(validate_snapshot(&payload.to_string()).is_err());
        payload["tasks"][0]["due"] = Value::String("2026-11-12".into());
        let original = payload["tasks"][0].clone();
        payload["tasks"].as_array_mut().unwrap().push(original);
        assert!(validate_snapshot(&payload.to_string()).is_err());
        assert!(validate_snapshot(&"x".repeat(MAX_SNAPSHOT_BYTES + 1)).is_err());
    }
}
