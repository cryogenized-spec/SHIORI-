//! Read-only audit of a staged Android-to-canonical migration.
//! The shadow database is never created or modified by this operation.
//! Audits both archived original data and the current WebView export.
//! An audit result is NOT permission to activate or delete a legacy store.

use chrono::{DateTime, Utc};
use rusqlite::{Connection, OpenFlags, OptionalExtension, params};
use serde_json::Value;
use std::{error::Error, path::Path};

use crate::validate_snapshot;

#[derive(Debug, PartialEq, Eq)]
pub enum ShadowAudit {
    Missing,
    Verified {
        tasks: usize,
        current_matches: bool,
        /// Older imports without any source timestamp cannot have every
        /// generated timestamp independently reconstructed.
        unverified_timestamps: usize,
    },
}

fn normalized_snapshot(raw: &str) -> Result<Value, Box<dyn Error>> {
    validate_snapshot(raw)?;
    let mut json: Value = serde_json::from_str(raw)?;
    json.as_object_mut()
        .ok_or("backup must be an object")?
        .remove("exported_at");
    Ok(json)
}

fn utc_timestamp(raw: &str) -> Result<String, Box<dyn Error>> {
    Ok(DateTime::parse_from_rfc3339(raw)?
        .with_timezone(&Utc)
        .to_rfc3339())
}

fn optional_time(task: &Value, key: &str) -> Result<Option<String>, Box<dyn Error>> {
    task.get(key)
        .and_then(Value::as_str)
        .map(utc_timestamp)
        .transpose()
}

/// Verify the unmodified archived backup against its canonical task rows.
/// Compare the current device export separately: current data may have changed
/// since staging, even when the shadow database remains healthy.
///
/// Open read-only; notably, a missing shadow path is not created.
pub fn audit_legacy_shadow(
    db_path: &Path,
    current_raw: &str,
) -> Result<ShadowAudit, Box<dyn Error>> {
    if !db_path.exists() {
        return Ok(ShadowAudit::Missing);
    }
    let current = normalized_snapshot(current_raw)?;
    let db = Connection::open_with_flags(db_path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let quick_check: String = db.query_row("PRAGMA quick_check", [], |row| row.get(0))?;
    if quick_check != "ok" {
        return Err("shadow database integrity check failed".into());
    }
    let schema: i64 = db.query_row("PRAGMA user_version", [], |row| row.get(0))?;
    if schema != 3 {
        return Err("unexpected shadow schema version".into());
    }
    let archived: String = db
        .query_row(
            "SELECT payload FROM legacy_shadow_source WHERE id = 1",
            [],
            |row| row.get(0),
        )
        .optional()?
        .ok_or("no archived migration source")?;
    let staged = normalized_snapshot(&archived)?;
    let source: Value = serde_json::from_str(&archived)?;
    let original_tasks = source["tasks"].as_array().ok_or("missing staged tasks")?;
    let task_count: i64 = db.query_row("SELECT COUNT(*) FROM tasks", [], |row| row.get(0))?;
    if task_count != original_tasks.len() as i64 {
        return Err("staged canonical task count mismatch".into());
    }

    let source_export = source.get("exported_at")
        .and_then(Value::as_str)
        .map(utc_timestamp)
        .transpose()?;
    let mut unverified_timestamps = 0usize;
    for original in original_tasks {
        let field = |key| original.get(key).and_then(Value::as_str).unwrap_or("");
        let id = field("id");
        let status = match field("status") {
            "progress" => "in_progress",
            "todo" => "todo",
            "done" => "done",
            _ => return Err("invalid archived task status".into()),
        };
        let due = field("due");
        let due_on = if due.is_empty() { None } else { Some(due) };
        let assignee = original.get("assigneeId")
            .and_then(Value::as_str)
            .map(str::trim);
        let minutes = original.get("mins").and_then(Value::as_i64);
        let version = match original.get("version").filter(|v| !v.is_null()) {
            None => 1,
            Some(v) => v.as_i64().filter(|v| *v > 0).ok_or("invalid archived revision")?,
        };

        let created = optional_time(original, "createdAt")?
            .or_else(|| source_export.clone());
        if created.is_none() { unverified_timestamps += 1; }
        let updated = optional_time(original, "updatedAt")?
            .or_else(|| created.clone());
        if updated.is_none() { unverified_timestamps += 1; }
        let completed = if status == "done" {
            let value = optional_time(original, "completedAt")?
                .or_else(|| updated.clone());
            if value.is_none() { unverified_timestamps += 1; }
            value
        } else {
            None
        };

        // Compare all canonical user fields, identities, revisions, dates,
        // stored timestamps when reconstructable, and absence of tombstones.
        // SQLite IS supports nullable due/assignee/effort values.
        let matches: i64 = db.query_row(
            "SELECT COUNT(*) FROM tasks WHERE id=?1
              AND title=?2 AND notes=?3 AND project=?4
              AND priority=?5 AND status=?6 AND due_on IS ?7
              AND estimate_minutes IS ?8 AND assignee_id IS ?9
              AND version=?10 AND deleted_at IS NULL
              AND (?11 IS NULL OR created_at=?11)
              AND (?12 IS NULL OR updated_at=?12)
              AND (?13 IS NULL OR completed_at=?13)
              AND ((?14='done' AND completed_at IS NOT NULL)
                   OR (?14!='done' AND completed_at IS NULL))",
            params![
                id,
                field("title").trim(),
                field("description"),
                field("project").trim(),
                field("priority"),
                status,
                due_on,
                minutes,
                assignee,
                version,
                created,
                updated,
                completed,
                status,
            ],
            |row| row.get(0),
        )?;
        if matches != 1 {
            return Err("staged canonical task field mismatch".into());
        }
    }

    Ok(ShadowAudit::Verified {
        tasks: original_tasks.len(),
        current_matches: staged == current,
        unverified_timestamps,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::migration::stage_legacy_backup;

    fn fixture() -> String {
        serde_json::json!({
            "format":"shiori-android-local-v1",
            "exported_at":"2026-11-12T18:00:00Z",
            "tasks":[{
                "id":"u1001", "title":"検査", "description":"Line one\nLine two",
                "project":"Personal", "priority":"high", "status":"progress",
                "due":"2026-11-15", "mins":45, "assigneeId":"local",
                "tags":["mobile"], "version":3
            }],
            "saved_views":[], "sort":"fifo"
        }).to_string()
    }

    fn path() -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "shiori-audit-{}-{}.sqlite3",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ))
    }

    #[test]
    fn missing_is_reported_without_creating_a_file() {
        let path = path();
        assert_eq!(
            audit_legacy_shadow(&path, &fixture()).unwrap(),
            ShadowAudit::Missing
        );
        assert!(!path.exists());
    }

    #[test]
    fn audits_export_timestamp_changes_and_detects_source_drift() {
        let path = path();
        let raw = fixture();
        stage_legacy_backup(&path, &raw).unwrap();
        let mut same: Value = serde_json::from_str(&raw).unwrap();
        same["exported_at"] = Value::from("2026-11-12T20:00:00Z");
        assert_eq!(
            audit_legacy_shadow(&path, &same.to_string()).unwrap(),
            ShadowAudit::Verified {
                tasks: 1,
                current_matches: true,
                unverified_timestamps: 0
            }
        );
        same["tasks"][0]["title"] = Value::from("New edit not yet staged");
        assert!(matches!(
            audit_legacy_shadow(&path, &same.to_string()).unwrap(),
            ShadowAudit::Verified {current_matches: false, ..}
        ));
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn detects_canonical_corruption_without_rewriting_it() {
        let path = path();
        let raw = fixture();
        stage_legacy_backup(&path, &raw).unwrap();
        let db = Connection::open(&path).unwrap();
        db.execute(
            "UPDATE tasks SET priority='low' WHERE id='u1001'", []
        ).unwrap();
        drop(db);
        assert!(audit_legacy_shadow(&path, &raw).is_err());
        let db = Connection::open(&path).unwrap();
        let priority: String = db.query_row(
            "SELECT priority FROM tasks WHERE id='u1001'", [], |r| r.get(0)
        ).unwrap();
        assert_eq!(priority, "low");
        drop(db);
        std::fs::remove_file(path).unwrap();
    }
}
