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
