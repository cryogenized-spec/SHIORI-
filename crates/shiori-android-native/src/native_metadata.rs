//! M2.4d: canonical Rust/SQLite owners for Android tags, saved views and
//! sorting. These writes never touch the archived legacy JSON or WebView.
use chrono::Utc;
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use serde_json::{Value, json};
use std::{collections::HashSet, error::Error, path::Path};

use crate::migration::read_android_metadata;

fn positive(value: &Value, key: &str) -> Result<i64, Box<dyn Error>> {
    value
        .get(key)
        .and_then(Value::as_i64)
        .filter(|v| *v > 0)
        .ok_or_else(|| format!("{key} must be a positive integer").into())
}

fn valid_tag(text: &str) -> bool {
    !text.is_empty()
        && text == text.trim()
        && text.chars().count() <= 40
        && !text.chars().any(char::is_control)
}

/// Fully replace the ordered tags of ONE live task in a single transaction.
/// The task's canonical version is advanced with CAS, preventing stale
/// tag writers from silently overwriting later task edits (and vice versa).
pub fn set_task_tags(path: &Path, input: &Value) -> Result<Value, Box<dyn Error>> {
    let id = input.get("id").and_then(Value::as_str).ok_or("missing task id")?;
    let expected = positive(input, "expected_version")?;
    let array = input.get("tags").and_then(Value::as_array).ok_or("missing tag list")?;
    if array.len() > 16 {
        return Err("a task may have no more than 16 tags".into());
    }
    let mut seen = HashSet::new();
    let mut tags = Vec::with_capacity(array.len());
    for item in array {
        let tag = item.as_str().ok_or("tags must be strings")?;
        if !valid_tag(tag) || !seen.insert(tag.to_lowercase()) {
            return Err("tag is empty, duplicated, too long or contains controls".into());
        }
        tags.push(tag.to_owned());
    }

    let mut db = Connection::open(path)?;
    db.execute_batch("PRAGMA foreign_keys=ON; PRAGMA busy_timeout=4000;")?;
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let updated = tx.execute(
        "UPDATE tasks SET updated_at=?3, version=version+1
         WHERE id=?1 AND version=?2 AND deleted_at IS NULL",
        params![id, expected, Utc::now().to_rfc3339()],
    )?;
    if updated != 1 {
        return Err("task changed or was removed; reload before changing tags".into());
    }
    tx.execute("DELETE FROM android_task_tags WHERE task_id=?1", params![id])?;
    for (position, tag) in tags.iter().enumerate() {
        tx.execute(
            "INSERT INTO android_task_tags(task_id,position,value) VALUES(?1,?2,?3)",
            params![id, i64::try_from(position)?, tag],
        )?;
    }
    tx.commit()?;
    Ok(json!({"ok":true,"id":id,"version":expected+1,"tags":tags}))
}

fn valid_view(entry: &Value) -> Result<(), Box<dyn Error>> {
    let obj = entry.as_object().ok_or("invalid saved view")?;
    const KEYS: &[&str] = &["name", "view", "filter", "sort", "query"];
    if obj.len() != KEYS.len() || obj.keys().any(|key| !KEYS.contains(&key.as_str())) {
        return Err("saved view contains unsupported fields".into());
    }
    let name = entry["name"].as_str().ok_or("saved view name missing")?;
    if name.trim() != name || name.is_empty() || name.chars().count() > 40
        || name.chars().any(char::is_control)
    {
        return Err("invalid saved view name".into());
    }
    if !matches!(entry["view"].as_str(), Some("today"|"attention"|"inbox"|"board")) {
        return Err("unsupported saved view type".into());
    }
    if !matches!(entry["filter"].as_str(), Some("all"|"low"|"medium"|"high"|"urgent")) {
        return Err("unsupported saved view filter".into());
    }
    if !matches!(entry["sort"].as_str(), Some("focus"|"fifo"|"due"|"priority")) {
        return Err("unsupported saved view ordering".into());
    }
    let query = entry["query"].as_str().ok_or("missing saved view query")?;
    if query.chars().count() > 240 || query.chars().any(char::is_control) {
        return Err("saved view query is too long or malformed".into());
    }
    Ok(())
}

/// Set the complete saved-view list and/or ordering with optimistic workspace
/// revision. Old M2.3 databases lack android_workspace_revision; the first
/// update adds only that table without touching original source archives.
pub fn set_workspace(path: &Path, input: &Value) -> Result<Value, Box<dyn Error>> {
    let expected = positive(input, "expected_revision")?;
    if input.get("saved_views").is_none() && input.get("sort").is_none() {
        return Err("no workspace preferences to update".into());
    }
    let mut db = Connection::open(path)?;
    db.execute_batch("PRAGMA busy_timeout=4000;")?;
    let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
    let (old_views, old_order): (String, String) = tx.query_row(
        "SELECT saved_views_json,sort_mode FROM android_workspace_metadata WHERE id=1",
        [], |row| Ok((row.get(0)?,row.get(1)?)),
    )?;
    let views: Value = match input.get("saved_views") {
        Some(value) => value.clone(),
        None => serde_json::from_str(&old_views)?,
    };
    let array = views.as_array().ok_or("saved views must be an array")?;
    if array.len() > 30 {
        return Err("saved views are limited to 30".into());
    }
    let mut names = HashSet::new();
    for entry in array {
        valid_view(entry)?;
        if !names.insert(entry["name"].as_str().unwrap().to_lowercase()) {
            return Err("duplicate saved view names".into());
        }
    }
    let order = match input.get("sort") {
        Some(value) => value.as_str().ok_or("invalid sort mode")?,
        None => &old_order,
    };
    if !matches!(order, "focus"|"fifo"|"due"|"priority") {
        return Err("unsupported sort mode".into());
    }
    tx.execute_batch(
        "CREATE TABLE IF NOT EXISTS android_workspace_revision (
            id INTEGER PRIMARY KEY CHECK(id=1),
            revision INTEGER NOT NULL CHECK(revision > 0)
        );"
    )?;
    tx.execute(
        "INSERT OR IGNORE INTO android_workspace_revision(id,revision) VALUES(1,1)", []
    )?;
    let revised = tx.execute(
        "UPDATE android_workspace_revision SET revision=revision+1
         WHERE id=1 AND revision=?1", params![expected]
    )?;
    if revised != 1 {
        return Err("workspace preferences changed; reload before saving".into());
    }
    tx.execute(
        "UPDATE android_workspace_metadata SET saved_views_json=?1,sort_mode=?2 WHERE id=1",
        params![serde_json::to_string(&views)?,order],
    )?;
    tx.commit()?;
    Ok(json!({"ok":true,"metadata":read_android_metadata(path)?}))
}

/// Backward-compatible read of the optional workspace revision table. The
/// version 1 default is valid for original M2.2/M2.3 native databases.
pub fn workspace_revision(db: &Connection) -> Result<i64, Box<dyn Error>> {
    let table: bool = db.query_row(
        "SELECT EXISTS(SELECT 1 FROM sqlite_master
         WHERE type='table' AND name='android_workspace_revision')",
        [], |row| row.get(0),
    )?;
    if !table {
        return Ok(1);
    }
    let rev: Option<i64> = db.query_row(
        "SELECT revision FROM android_workspace_revision WHERE id=1",
        [], |row| row.get(0),
    ).optional()?;
    let result = rev.ok_or("workspace revision row is missing")?;
    if result < 1 {
        return Err("invalid workspace revision".into());
    }
    Ok(result)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{
        export::export_working_database,
        migration::read_android_metadata,
        recovery::recover_to_separate_preview,
        working_copy::{initialize_working_copy, working_request},
    };

    fn paths() -> (std::path::PathBuf, std::path::PathBuf, std::path::PathBuf) {
        let suffix = format!(
            "{}-{}", std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        );
        let root = std::env::temp_dir();
        (
            root.join(format!("shiori-meta-src-{suffix}.sqlite3")),
            root.join(format!("shiori-meta-export-{suffix}.sqlite3")),
            root.join(format!("shiori-meta-recover-{suffix}.sqlite3")),
        )
    }
    fn source() -> String {
        json!({
            "format":"shiori-android-local-v1",
            "exported_at":"2026-11-13T10:00:00Z",
            "tasks":[{
                "id":"u-tag","title":"Native tags","project":"Personal",
                "description":"Archived unchanged","priority":"medium",
                "status":"todo","due":"","tags":["Legacy"]
            }],
            "saved_views":[{"name":"Mine","view":"inbox","filter":"all",
                "sort":"fifo","query":""}],
            "sort":"fifo"
        }).to_string()
    }
    fn send(path: &Path, value: Value) -> Result<Value, Box<dyn Error>> {
        let mut request=value;
        request["protocol"]=json!("shiori-native-working-v1");
        working_request(path, &request.to_string())
    }

    #[test]
    fn tags_are_atomic_revision_checked_ordered_and_durable() {
        let (path, export, recovered) = paths();
        let legacy = source();
        initialize_working_copy(&path, &legacy).unwrap();
        assert_eq!(read_android_metadata(&path).unwrap()["revision"], 1);
        assert_eq!(
            read_android_metadata(&path).unwrap()["tags_by_id"]["u-tag"],
            json!(["Legacy"])
        );
        let before = send(&path,json!({"op":"list"})).unwrap();
        let version=before["tasks"][0]["version"].as_i64().unwrap();
        let response=send(&path,json!({
            "op":"tags_set","id":"u-tag","expected_version":version,
            "tags":["Native","Quality","栞"]
        })).unwrap();
        assert_eq!(response["version"],version+1);
        assert_eq!(response["tags"],json!(["Native","Quality","栞"]));
        for bad in [
            json!({"op":"tags_set","id":"u-tag","expected_version":version,"tags":["stale"]}),
            json!({"op":"tags_set","id":"u-tag","expected_version":version+1,"tags":["X","x"]}),
            json!({"op":"tags_set","id":"u-tag","expected_version":version+1,"tags":["bad\nline"]}),
            json!({"op":"tags_set","id":"u-tag","expected_version":version+1,"tags":[""]}),
            json!({"op":"tags_set","id":"missing","expected_version":version+1,"tags":[]}),
            json!({"op":"tags_set","id":"u-tag","expected_version":version+1,
                "tags":(0..17).map(|n|n.to_string()).collect::<Vec<_>>()})
        ] {
            assert!(send(&path,bad).is_err());
        }
        assert_eq!(
            read_android_metadata(&path).unwrap()["tags_by_id"]["u-tag"],
            json!(["Native","Quality","栞"])
        );
        assert_eq!(
            send(&path,json!({"op":"list"})).unwrap()["tasks"][0]["version"],
            version+1
        );
        assert!(send(&path,json!({
            "op":"edit","id":"u-tag","expected_version":version,"title":"stale"
        })).is_err());
        assert_eq!(
            send(&path,json!({"op":"metadata"})).unwrap()["metadata"]["revision"],1
        );
        export_working_database(&path,&export).unwrap();
        recover_to_separate_preview(&export,&recovered).unwrap();
        assert_eq!(
            read_android_metadata(&recovered).unwrap()["tags_by_id"]["u-tag"],
            json!(["Native","Quality","栞"])
        );
        assert_eq!(
            read_android_metadata(&recovered).unwrap()["revision"],1
        );
        let store=shiori_storage::SqliteStore::open(&path).unwrap();
        assert_eq!(store.legacy_shadow_source().unwrap().as_deref(),Some(legacy.as_str()));
        drop(store);
        for file in [path,export,recovered] {std::fs::remove_file(file).unwrap();}
    }

    #[test]
    fn workspace_preferences_are_revision_guarded_and_backed_up() {
        let (path,export,recovered)=paths();
        initialize_working_copy(&path,&source()).unwrap();
        assert_eq!(read_android_metadata(&path).unwrap()["revision"],1);
        let changed=send(&path,json!({
            "op":"workspace_set","expected_revision":1,"sort":"priority",
            "saved_views":[
                {"name":"Urgent","view":"attention","filter":"high",
                 "sort":"priority","query":"Quality"}
            ]
        })).unwrap();
        assert_eq!(changed["metadata"]["revision"],2);
        assert_eq!(changed["metadata"]["sort"],"priority");
        assert_eq!(changed["metadata"]["saved_views"][0]["name"],"Urgent");
        assert_eq!(read_android_metadata(&path).unwrap()["revision"],2);
        for bad in [
            json!({"op":"workspace_set","expected_revision":1,"sort":"fifo"}),
            json!({"op":"workspace_set","expected_revision":2,"sort":"unknown"}),
            json!({"op":"workspace_set","expected_revision":2,"saved_views":[
                {"name":"Duplicate","view":"today","filter":"all","sort":"fifo","query":""},
                {"name":"duplicate","view":"today","filter":"all","sort":"fifo","query":""}
            ]}),
            json!({"op":"workspace_set","expected_revision":2,"saved_views":[
                {"name":"Extra","view":"today","filter":"all",
                 "sort":"fifo","query":"","unexpected":true}
            ]}),
            json!({"op":"workspace_set","expected_revision":2})
        ] {
            assert!(send(&path,bad).is_err());
        }
        assert_eq!(read_android_metadata(&path).unwrap()["revision"],2);
        let final_state=send(&path,json!({
            "op":"workspace_set","expected_revision":2,"saved_views":[]
        })).unwrap();
        assert_eq!(final_state["metadata"]["revision"],3);
        assert_eq!(final_state["metadata"]["sort"],"priority");
        assert_eq!(final_state["metadata"]["saved_views"],json!([]));
        export_working_database(&path,&export).unwrap();
        recover_to_separate_preview(&export,&recovered).unwrap();
        assert_eq!(read_android_metadata(&path).unwrap(),read_android_metadata(&recovered).unwrap());
        assert_eq!(read_android_metadata(&recovered).unwrap()["revision"],3);
        for file in [path,export,recovered] {std::fs::remove_file(file).unwrap();}
    }

    #[test]
    fn older_native_database_without_revision_table_is_compatible() {
        let (path,_,_)=paths();
        initialize_working_copy(&path,&source()).unwrap();
        assert_eq!(workspace_revision(&Connection::open(&path).unwrap()).unwrap(),1);
        let updated=send(&path,json!({
            "op":"workspace_set","expected_revision":1,"sort":"due"
        })).unwrap();
        assert_eq!(updated["metadata"]["revision"],2);
        assert_eq!(updated["metadata"]["tags_by_id"]["u-tag"],json!(["Legacy"]));
        std::fs::remove_file(path).unwrap();
    }
}
