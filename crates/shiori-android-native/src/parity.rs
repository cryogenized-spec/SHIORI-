//! Explicit M2.2 preflight for a fresh, non-authoritative native cutover
//! candidate. Unknown legacy fields and source drift fail closed.
use serde_json::{Value, json};
use std::{collections::BTreeSet, error::Error, path::Path};

use crate::{
    audit::{ShadowAudit, audit_legacy_shadow},
    migration::stage_legacy_backup,
    validate_snapshot,
};

const TASK_KEYS: &[&str] = &[
    "id",
    "title",
    "description",
    "project",
    "priority",
    "status",
    "due",
    "tags",
    "mins",
    "assigneeId",
    "version",
    "createdAt",
    "updatedAt",
    "completedAt",
];
const VIEW_KEYS: &[&str] = &["name", "view", "filter", "sort", "query"];
const ROOT_KEYS: &[&str] = &["format", "exported_at", "tasks", "saved_views", "sort"];

/// Validates canonical mapping, immutable original snapshot preservation,
/// first-class SQLite task tags and saved workspace preferences.
///
/// Does NOT activate a database or overwrite the source. A pre-existing
/// candidate is audited rather than silently replaced. The returned
/// readiness flag may be used by a separately reviewed opt-in cutover.
pub fn preflight(path: &Path, current: &str) -> Result<Value, Box<dyn Error>> {
    validate_snapshot(current)?;
    if !path.exists() {
        stage_legacy_backup(path, current)?;
    }
    let source: Value = serde_json::from_str(current)?;
    let mut unsupported = BTreeSet::<String>::new();
    for key in source.as_object().ok_or("expected root")?.keys() {
        if !ROOT_KEYS.contains(&key.as_str()) {
            unsupported.insert(format!("backup.{key}"));
        }
    }
    let mut tags = 0_usize;
    for task in source["tasks"].as_array().ok_or("missing task list")? {
        for key in task.as_object().ok_or("invalid task record")?.keys() {
            if !TASK_KEYS.contains(&key.as_str()) {
                unsupported.insert(format!("task.{key}"));
            }
        }
        tags += task
            .get("tags")
            .and_then(Value::as_array)
            .map_or(0, Vec::len);
    }
    for view in source["saved_views"]
        .as_array()
        .ok_or("missing saved views")?
    {
        for key in view.as_object().ok_or("invalid saved view")?.keys() {
            if !VIEW_KEYS.contains(&key.as_str()) {
                unsupported.insert(format!("saved_view.{key}"));
            }
        }
    }

    let (task_count, same, inferred) = match audit_legacy_shadow(path, current)? {
        ShadowAudit::Verified {
            tasks,
            current_matches,
            unverified_timestamps,
        } => (tasks, current_matches, unverified_timestamps),
        ShadowAudit::Missing => return Err("no staged migration database exists".into()),
    };
    let safe = same && unsupported.is_empty();
    Ok(json!({
        "ok": true,
        "ready": safe,
        "matches_live_android_source": same,
        "task_records": task_count,
        "tag_records": tags,
        "saved_views": source["saved_views"].as_array().map_or(0, Vec::len),
        "sort_mode": source["sort"],
        "inferred_timestamp_fields": inferred,
        "archived_legacy_and_native_metadata_verified": true,
        "unsupported_fields": unsupported.into_iter().collect::<Vec<_>>(),
        "reason": if !same {
            "Android tasks changed after candidate staging; no source cutover allowed"
        } else if !safe {
            "Unsupported legacy fields would lack an editable native mapping"
        } else {
            "Canonical task rows, tags, saved views and source archive verified"
        }
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;
    use shiori_storage::SqliteStore;

    fn path() -> std::path::PathBuf {
        std::env::temp_dir().join(format!(
            "shiori-parity-{}-{}.sqlite3",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        ))
    }
    fn input() -> String {
        json!({
            "format":"shiori-android-local-v1",
            "exported_at":"2026-11-13T10:00:00Z",
            "sort":"priority",
            "saved_views":[{"name":"Top priority","view":"inbox",
                            "filter":"high","sort":"priority","query":""}],
            "tasks":[{
                "id":"legacy-1","title":"Existing task","project":"Android",
                "description":"Keep notes","priority":"high","status":"progress",
                "tags":["Local","Repair"],"due":"2026-11-17","mins":30,
                "assigneeId":"local","version":4,
                "createdAt":"2026-11-12T09:00:00Z","updatedAt":"2026-11-13T09:00:00Z"
            }]
        })
        .to_string()
    }

    #[test]
    fn parity_maps_tags_views_sort_revision_and_timestamps_without_data_loss() {
        let path = path();
        let data = input();
        let report = preflight(&path, &data).unwrap();
        assert_eq!(report["ready"], true);
        assert_eq!(report["task_records"], 1);
        assert_eq!(report["tag_records"], 2);
        assert_eq!(report["saved_views"], 1);
        assert_eq!(report["inferred_timestamp_fields"], 0);
        let meta = crate::migration::read_android_metadata(&path).unwrap();
        assert_eq!(meta["tags_by_id"]["legacy-1"], json!(["Local", "Repair"]));
        assert_eq!(meta["sort"], "priority");
        let original = SqliteStore::open(&path)
            .unwrap()
            .legacy_shadow_source()
            .unwrap()
            .unwrap();
        assert_eq!(original, data);
        // Only the regenerated export timestamp differs: this remains
        // identical from the user's task/view perspective.
        let mut reexport: Value = serde_json::from_str(&data).unwrap();
        reexport["exported_at"] = json!("2026-11-13T10:03:00Z");
        assert_eq!(
            preflight(&path, &reexport.to_string()).unwrap()["ready"],
            true
        );
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn unknown_fields_and_stale_source_refuse_cutover() {
        let path = path();
        let mut extra: Value = serde_json::from_str(&input()).unwrap();
        extra["tasks"][0]["unknownRecurringRule"] = json!("weekly");
        let preview = preflight(&path, &extra.to_string()).unwrap();
        assert_eq!(preview["ready"], false);
        assert_eq!(
            preview["unsupported_fields"],
            json!(["task.unknownRecurringRule"])
        );
        extra["tasks"][0]
            .as_object_mut()
            .unwrap()
            .remove("unknownRecurringRule");
        assert_eq!(
            preflight(&path, &extra.to_string()).unwrap()["ready"],
            false
        );
        assert_eq!(
            preflight(&path, &extra.to_string()).unwrap()["matches_live_android_source"],
            false
        );
        std::fs::remove_file(path).unwrap();
    }

    #[test]
    fn tampered_native_tags_or_preferences_block_preflight() {
        let path = path();
        let data = input();
        assert_eq!(preflight(&path, &data).unwrap()["ready"], true);
        let db = rusqlite::Connection::open(&path).unwrap();
        db.execute(
            "UPDATE android_task_tags SET value='Changed' WHERE position=0",
            [],
        )
        .unwrap();
        assert!(preflight(&path, &data).is_err());
        db.execute(
            "UPDATE android_task_tags SET value='Local' WHERE position=0",
            [],
        )
        .unwrap();
        db.execute("UPDATE android_workspace_metadata SET sort_mode='fifo'", [])
            .unwrap();
        assert!(preflight(&path, &data).is_err());
        std::fs::remove_file(path).unwrap();
    }
}
