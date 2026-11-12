//! Separate, opt-in Rust/SQLite task working copy for Android M2.
//! Never reads from or writes to the live WebView task store, native safety
//! vault, or immutable canonical migration shadow. Only Kotlin supplies the
//! app-private database path; there is no JavaScript/native object bridge.
use chrono::NaiveDate;
use serde_json::{Value, json};
use shiori_core::{Priority, Task, TaskPatch, TaskStatus, validate_assignee_id, validate_estimate};
use shiori_storage::{SqliteStore, TaskFilter};
use std::{error::Error, path::Path, str::FromStr};

use crate::migration::stage_legacy_backup;

const MAX_REQUEST_BYTES: usize = 16_384;
const MAX_VISIBLE_TASKS: usize = 50;
const PROTOCOL: &str = "shiori-native-working-v1";

/// Seed a *third*, separately named SQLite file from the existing Android
/// snapshot. Initial import and archival are transactionally atomic.
/// Once it exists, never silently replace it with changed phone data.
pub fn initialize_working_copy(
    target: &Path,
    original_backup: &str,
) -> Result<String, Box<dyn Error>> {
    crate::validate_snapshot(original_backup)?;
    if target.exists() {
        let existing = SqliteStore::open(target)?;
        if existing.legacy_shadow_source()?.is_some() {
            return Ok(
                "Rust working copy already exists; no existing edits were overwritten".into(),
            );
        }
    }
    let report = stage_legacy_backup(target, original_backup)?;
    Ok(format!(
        "Editable Rust working copy created: {} task(s). Original Android tasks were not changed.",
        report.imported
    ))
}

fn requested<'a>(obj: &'a Value, name: &str) -> Result<&'a str, Box<dyn Error>> {
    Ok(obj
        .get(name)
        .and_then(Value::as_str)
        .ok_or("missing or invalid string field")?)
}
fn version(obj: &Value) -> Result<i64, Box<dyn Error>> {
    obj.get("expected_version")
        .and_then(Value::as_i64)
        .filter(|v| *v > 0)
        .ok_or_else(|| "expected_version must be a positive integer".into())
}
fn date(raw: &str) -> Result<Option<NaiveDate>, Box<dyn Error>> {
    if raw.is_empty() {
        Ok(None)
    } else {
        Ok(Some(NaiveDate::parse_from_str(raw, "%Y-%m-%d")?))
    }
}
fn summary(t: Task) -> Value {
    json!({
        "id": t.id, "title": t.title, "project": t.project, "notes": t.notes,
        "priority": t.priority.as_str(), "status": t.status.as_str(),
        "due_on": t.due_on, "estimate_minutes": t.estimate_minutes,
        "assignee_id": t.assignee_id, "version": t.version
    })
}
/// Bounded, versioned native-only command protocol. Mutations are performed
/// through the same shiori-storage domain functions as the desktop CLI.
pub fn working_request(path: &Path, request: &str) -> Result<Value, Box<dyn Error>> {
    if request.len() > MAX_REQUEST_BYTES {
        return Err("working request exceeds size limit".into());
    }
    let input: Value = serde_json::from_str(request)?;
    if input.get("protocol").and_then(Value::as_str) != Some(PROTOCOL) {
        return Err("unsupported native working protocol".into());
    }
    // Listing must not create a new file after an interrupted initialization.
    if !path.exists() {
        return Err("create a Rust working copy before using native tasks".into());
    }
    let store = SqliteStore::open(path)?;
    if store.legacy_shadow_source()?.is_none() {
        return Err("native working database has no original backup; refusing writes".into());
    }
    let op = requested(&input, "op")?;
    match op {
        "list" => {
            let all = store.list(TaskFilter::default())?;
            let total = all.len();
            let tasks: Vec<Value> = all
                .into_iter()
                .take(MAX_VISIBLE_TASKS)
                .map(summary)
                .collect();
            Ok(json!({"ok":true,"tasks":tasks,"total":total}))
        }
        "create" => {
            let title = requested(&input, "title")?;
            let project = requested(&input, "project")?;
            let priority = Priority::from_str(requested(&input, "priority")?)?;
            let due = input.get("due_on").and_then(Value::as_str).unwrap_or("");
            let mut task = Task::new(title, project, priority, date(due)?)?;
            if let Some(notes) = input.get("notes").and_then(Value::as_str) {
                if notes.chars().count() > 6000 {
                    return Err("task notes exceed 6000 characters".into());
                }
                task.notes = notes.into();
            }
            if let Some(minutes) = input.get("estimate_minutes").filter(|v| !v.is_null()) {
                task.estimate_minutes = Some(validate_estimate(
                    minutes.as_i64().ok_or("invalid estimate")?,
                )?);
            }
            if let Some(assignee) = input.get("assignee_id").and_then(Value::as_str) {
                task.assignee_id = Some(validate_assignee_id(assignee)?);
            }
            store.insert(&task)?;
            Ok(json!({"ok":true,"task":summary(task)}))
        }
        "rename" => {
            let task = store.edit_if_version(
                requested(&input, "id")?,
                version(&input)?,
                TaskPatch {
                    title: Some(requested(&input, "title")?.into()),
                    ..TaskPatch::default()
                },
            )?;
            Ok(json!({"ok":true,"task":summary(task)}))
        }
        "status" => {
            let task = store.set_status_if_version(
                requested(&input, "id")?,
                version(&input)?,
                TaskStatus::from_str(requested(&input, "status")?)?,
            )?;
            Ok(json!({"ok":true,"task":summary(task)}))
        }
        "delete" => {
            store.delete_if_version(requested(&input, "id")?, version(&input)?)?;
            Ok(json!({"ok":true,"deleted":true}))
        }
        _ => Err("unknown native working operation".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    fn location() -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "shiori-native-working-{}-{}.sqlite3",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ))
    }
    fn backup() -> String {
        json!({
            "format":"shiori-android-local-v1",
            "exported_at":"2026-11-12T18:00:00Z",
            "tasks":[{
                "id":"u123", "title":"Legacy 栞", "project":"Android",
                "description":"Keep this", "status":"todo", "priority":"high",
                "due":"", "tags":[]
            }],
            "saved_views":[], "sort":"fifo"
        })
        .to_string()
    }
    fn command(op: &str) -> Value {
        json!({"protocol":PROTOCOL, "op":op})
    }
    fn send(path: &Path, command: Value) -> Result<Value, Box<dyn Error>> {
        working_request(path, &command.to_string())
    }

    #[test]
    fn native_crud_is_durable_revisions_are_checked_and_deletions_leave_tombstones() {
        let path = location();
        let backup = backup();
        assert!(send(&path, command("list")).is_err());
        assert!(!path.exists());
        initialize_working_copy(&path, &backup).unwrap();
        let original = send(&path, command("list")).unwrap();
        assert_eq!(original["total"], 1);
        assert_eq!(original["tasks"][0]["title"], "Legacy 栞");
        let created = send(
            &path,
            json!({
                "protocol":PROTOCOL, "op":"create",
                "title":"Native record", "project":"Personal", "priority":"medium",
                "notes":"Unicode café", "estimate_minutes":35
            }),
        )
        .unwrap();
        let id = created["task"]["id"].as_str().unwrap().to_owned();
        let first_version = created["task"]["version"].as_i64().unwrap();
        let renamed = send(
            &path,
            json!({
                "protocol":PROTOCOL, "op":"rename",
                "id":id, "title":"Native edited", "expected_version":first_version
            }),
        )
        .unwrap();
        let second_version = renamed["task"]["version"].as_i64().unwrap();
        assert!(second_version > first_version);
        assert!(
            send(
                &path,
                json!({
                    "protocol":PROTOCOL, "op":"delete",
                    "id":id, "expected_version":first_version
                })
            )
            .is_err()
        );
        let completed = send(
            &path,
            json!({
                "protocol":PROTOCOL, "op":"status",
                "id":id, "status":"done", "expected_version":second_version
            }),
        )
        .unwrap();
        let third_version = completed["task"]["version"].as_i64().unwrap();
        assert_eq!(completed["task"]["status"], "done");
        assert!(
            send(
                &path,
                json!({
                    "protocol":PROTOCOL, "op":"status",
                    "id":id, "status":"todo", "expected_version":second_version
                })
            )
            .is_err()
        );
        send(
            &path,
            json!({
                "protocol":PROTOCOL, "op":"delete",
                "id":id, "expected_version":third_version
            }),
        )
        .unwrap();
        let records = send(&path, command("list")).unwrap();
        assert_eq!(records["total"], 1);
        let store = SqliteStore::open(&path).unwrap();
        assert!(
            store
                .list(TaskFilter {
                    include_deleted: true,
                    ..TaskFilter::default()
                })
                .unwrap()
                .iter()
                .any(|task| task.id == id && task.deleted_at.is_some())
        );
        assert_eq!(
            store.legacy_shadow_source().unwrap().as_deref(),
            Some(backup.as_str())
        );
        drop(store);
        // Restart and inspect persisted user data and archived backup.
        assert_eq!(send(&path, command("list")).unwrap()["total"], 1);
        let mut new_backup: Value = serde_json::from_str(&backup).unwrap();
        new_backup["tasks"][0]["title"] = json!("Changed on phone");
        initialize_working_copy(&path, &new_backup.to_string()).unwrap();
        assert_eq!(
            send(&path, command("list")).unwrap()["tasks"][0]["title"],
            "Legacy 栞"
        );
        std::fs::remove_file(&path).unwrap();
    }

    #[test]
    fn invalid_commands_and_imports_do_not_damage_archived_tasks() {
        let path = location();
        initialize_working_copy(&path, &backup()).unwrap();
        for bad in [
            json!({"protocol":"unknown", "op":"list"}),
            json!({"protocol":PROTOCOL,"op":"create","title":"","project":"X","priority":"high"}),
            json!({"protocol":PROTOCOL,"op":"create","title":"a","project":"X","priority":"invalid"}),
            json!({"protocol":PROTOCOL,"op":"create","title":"a","project":"X","priority":"low","due_on":"2026-02-30"}),
            json!({"protocol":PROTOCOL,"op":"delete","id":"u123","expected_version":-1}),
            json!({"protocol":PROTOCOL,"op":"unknown"}),
        ] {
            assert!(send(&path, bad).is_err());
        }
        assert_eq!(send(&path, command("list")).unwrap()["total"], 1);
        std::fs::remove_file(path).unwrap();
    }
}
