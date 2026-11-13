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
const PAGE_SIZE: usize = 50;
const MAX_NATIVE_TASKS: usize = 5_000;
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
        "assignee_id": t.assignee_id, "version": t.version,
        "created_at": t.created_at, "updated_at": t.updated_at,
        "completed_at": t.completed_at
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
        "metadata" => {
            let data = crate::migration::read_android_metadata(path)?;
            Ok(json!({"ok":true, "metadata":data}))
        }
        "list" => {
            let requested_offset = input.get("offset").map_or(Ok(0_u64), |raw| {
                raw.as_u64().ok_or("offset must be an unsigned integer")
            })?;
            let offset = usize::try_from(requested_offset)?;
            if offset > MAX_NATIVE_TASKS {
                return Err("native task offset is above the 5000-record safety bound".into());
            }
            // Stable identity order for offset paging. Do not rely on the
            // ordinary filtered list's due-date/priority ordering.
            let mut all = store.list(TaskFilter::default())?;
            all.sort_by(|a, b| a.id.cmp(&b.id));
            let total = all.len();
            if total > MAX_NATIVE_TASKS {
                return Err(
                    "native source exceeds 5000 tasks; pagination safety limit reached".into(),
                );
            }
            if offset > total {
                return Err("offset is beyond the native task count".into());
            }
            // Non-cryptographic consistency token, not an authenticity or
            // backup checksum. Every domain mutation bumps the revision.
            // The client refuses mixed-page results if a task changes.
            let mut fingerprint = 14_695_981_039_346_656_037_u64;
            for task in &all {
                let marker = format!(
                    "{}:{}:{}:{};",
                    task.id.len(),
                    task.id,
                    task.version,
                    task.updated_at.to_rfc3339()
                );
                for byte in marker.bytes() {
                    fingerprint ^= u64::from(byte);
                    fingerprint = fingerprint.wrapping_mul(1_099_511_628_211);
                }
            }
            let snapshot = format!("{fingerprint:016x}-{total}");
            let expected = input.get("snapshot").and_then(Value::as_str);
            if offset != 0 && expected.is_none() {
                return Err("continuing a page requires the original snapshot token".into());
            }
            if let Some(expected) = expected
                && expected != snapshot
            {
                return Err(
                    "native tasks changed during paging; restart from the first page".into(),
                );
            }
            let next_offset = if offset + PAGE_SIZE < total {
                Some(offset + PAGE_SIZE)
            } else {
                None
            };
            let tasks: Vec<Value> = all
                .into_iter()
                .skip(offset)
                .take(PAGE_SIZE)
                .map(summary)
                .collect();
            Ok(json!({
                "ok":true,"tasks":tasks,"total":total,"offset":offset,
                "next_offset":next_offset,"snapshot":snapshot
            }))
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
        "edit" => {
            let present_string = |key: &str| -> Result<Option<String>, Box<dyn Error>> {
                match input.get(key) {
                    Some(v) => Ok(Some(v.as_str().ok_or("invalid text field")?.to_owned())),
                    None => Ok(None),
                }
            };
            let notes = present_string("notes")?;
            if notes
                .as_ref()
                .is_some_and(|value| value.chars().count() > 6000)
            {
                return Err("task notes exceed 6000 characters".into());
            }
            let priority = input
                .get("priority")
                .map(|v| -> Result<Priority, Box<dyn Error>> {
                    Ok(Priority::from_str(v.as_str().ok_or("invalid priority")?)?)
                })
                .transpose()?;
            let due_on = input
                .get("due_on")
                .map(|v| -> Result<Option<NaiveDate>, Box<dyn Error>> {
                    if v.is_null() {
                        Ok(None)
                    } else {
                        date(v.as_str().ok_or("invalid due date")?)
                    }
                })
                .transpose()?;
            let estimate_minutes = input
                .get("estimate_minutes")
                .map(|v| -> Result<Option<i64>, Box<dyn Error>> {
                    if v.is_null() {
                        Ok(None)
                    } else {
                        Ok(Some(validate_estimate(
                            v.as_i64().ok_or("invalid effort")?,
                        )?))
                    }
                })
                .transpose()?;
            let assignee_id = input
                .get("assignee_id")
                .map(|v| -> Result<Option<String>, Box<dyn Error>> {
                    if v.is_null() {
                        Ok(None)
                    } else {
                        Ok(Some(validate_assignee_id(
                            v.as_str().ok_or("invalid assignee")?,
                        )?))
                    }
                })
                .transpose()?;
            let task = store.edit_if_version(
                requested(&input, "id")?,
                version(&input)?,
                TaskPatch {
                    title: present_string("title")?,
                    notes,
                    project: present_string("project")?,
                    priority,
                    due_on,
                    estimate_minutes,
                    assignee_id,
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
    fn paginated_native_read_is_stable_complete_and_detects_writes() {
        let path = location();
        initialize_working_copy(&path, &backup()).unwrap();
        {
            let store = SqliteStore::open(&path).unwrap();
            for index in 0..122 {
                let task = Task::new(
                    &format!("Page task {index:03}"),
                    "Pagination",
                    Priority::Low,
                    None,
                )
                .unwrap();
                store.insert(&task).unwrap();
            }
        }

        let first = send(&path, command("list")).unwrap();
        assert_eq!(first["total"], 123);
        assert_eq!(first["offset"], 0);
        assert_eq!(first["next_offset"], 50);
        assert_eq!(first["tasks"].as_array().unwrap().len(), 50);
        let token = first["snapshot"].as_str().unwrap().to_owned();
        let mut ids: Vec<String> = first["tasks"]
            .as_array()
            .unwrap()
            .iter()
            .map(|row| row["id"].as_str().unwrap().to_owned())
            .collect();

        let second = send(
            &path,
            json!({
                "protocol":PROTOCOL,"op":"list","offset":50,"snapshot":token
            }),
        )
        .unwrap();
        assert_eq!(second["total"], 123);
        assert_eq!(second["next_offset"], 100);
        assert_eq!(second["snapshot"], token);
        ids.extend(
            second["tasks"]
                .as_array()
                .unwrap()
                .iter()
                .map(|row| row["id"].as_str().unwrap().to_owned()),
        );
        let third = send(
            &path,
            json!({
                "protocol":PROTOCOL,"op":"list","offset":100,"snapshot":token
            }),
        )
        .unwrap();
        assert!(third["next_offset"].is_null());
        assert_eq!(third["tasks"].as_array().unwrap().len(), 23);
        ids.extend(
            third["tasks"]
                .as_array()
                .unwrap()
                .iter()
                .map(|row| row["id"].as_str().unwrap().to_owned()),
        );
        assert_eq!(ids.len(), 123);
        let mut sorted = ids.clone();
        sorted.sort();
        sorted.dedup();
        assert_eq!(ids, sorted);

        // No unchecked offsets, missing token, or wrong snapshot.
        for request in [
            json!({"protocol":PROTOCOL,"op":"list","offset":50}),
            json!({"protocol":PROTOCOL,"op":"list","offset":50,"snapshot":"fake"}),
            json!({"protocol":PROTOCOL,"op":"list","offset":-1}),
            json!({"protocol":PROTOCOL,"op":"list","offset":0.5}),
            json!({"protocol":PROTOCOL,"op":"list","offset":5001}),
            json!({"protocol":PROTOCOL,"op":"list","offset":124}),
        ] {
            assert!(send(&path, request).is_err());
        }

        let row = first["tasks"][0].clone();
        let edited = send(
            &path,
            json!({
                "protocol":PROTOCOL,"op":"rename",
                "id":row["id"],"title":"Changed between pages",
                "expected_version":row["version"]
            }),
        )
        .unwrap();
        assert!(edited["ok"].as_bool().unwrap());
        assert!(
            send(
                &path,
                json!({
                    "protocol":PROTOCOL,"op":"list","offset":50,"snapshot":token
                })
            )
            .is_err()
        );
        let restart = send(&path, command("list")).unwrap();
        assert_ne!(restart["snapshot"], token);
        std::fs::remove_file(&path).unwrap();
    }

    #[test]
    fn native_full_edit_and_metadata_are_version_checked_and_preserve_tags() {
        let path = location();
        let mut source: Value = serde_json::from_str(&backup()).unwrap();
        source["tasks"][0]["tags"] = json!(["Original", "Native"]);
        source["saved_views"] = json!([{
            "name":"Mine","view":"inbox","filter":"all","sort":"fifo","query":""
        }]);
        initialize_working_copy(&path, &source.to_string()).unwrap();
        let metadata = send(&path, command("metadata")).unwrap();
        assert_eq!(
            metadata["metadata"]["tags_by_id"]["u123"],
            json!(["Original", "Native"])
        );
        assert_eq!(
            metadata["metadata"]["saved_views"]
                .as_array()
                .unwrap()
                .len(),
            1
        );
        let before = send(&path, command("list")).unwrap();
        let rev = before["tasks"][0]["version"].as_i64().unwrap();
        let changed = send(
            &path,
            json!({
                "protocol":PROTOCOL, "op":"edit", "id":"u123",
                "expected_version":rev,
                "title":"Updated via normal UI", "notes":"Preserve Unicode 栞",
                "project":"New home", "priority":"urgent",
                "due_on":"2026-12-11", "estimate_minutes":50,
                "assignee_id":"local"
            }),
        )
        .unwrap();
        assert_eq!(changed["task"]["notes"], "Preserve Unicode 栞");
        assert_eq!(changed["task"]["priority"], "urgent");
        assert_eq!(changed["task"]["estimate_minutes"], 50);
        assert_eq!(changed["task"]["assignee_id"], "local");
        assert!(changed["task"]["created_at"].is_string());
        assert!(
            send(
                &path,
                json!({
                    "protocol":PROTOCOL,"op":"edit","id":"u123",
                    "expected_version":rev,"notes":"Stale writer"
                })
            )
            .is_err()
        );
        assert!(
            send(
                &path,
                json!({
                    "protocol":PROTOCOL,"op":"edit","id":"u123",
                    "expected_version":changed["task"]["version"],
                    "estimate_minutes":0
                })
            )
            .is_err()
        );
        assert_eq!(
            send(&path, command("metadata")).unwrap()["metadata"]["tags_by_id"]["u123"],
            json!(["Original", "Native"])
        );
        std::fs::remove_file(path).unwrap();
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
