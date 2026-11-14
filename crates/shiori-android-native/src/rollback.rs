//! Read-only validation before switching a debug Android canary back to the
//! untouched WebView task source. Never creates/replaces a database file.
use rusqlite::{Connection, OpenFlags};
use std::{error::Error, fs, path::Path};

use crate::{
    audit::{ShadowAudit, audit_legacy_shadow, normalized_snapshot},
    validate_snapshot,
};

const MAX_ROLLBACK_VAULT_BYTES: u64 = 8 * 1024 * 1024;

/// Refuse UI rollback unless all three independently stored representations
/// agree: current WebView localStorage export, private pre-cutover SQLite
/// rollback vault, and immutable canonical migration candidate.
/// Ignores only the regenerated export timestamp.
pub fn verify_legacy_rollback(
    vault_path: &Path,
    candidate_path: &Path,
    current_raw: &str,
) -> Result<(), Box<dyn Error>> {
    validate_snapshot(current_raw)?;
    if !vault_path.is_file() || !candidate_path.is_file() {
        return Err("missing independent rollback vault or migration candidate".into());
    }
    let size = fs::metadata(vault_path)?.len();
    if size == 0 || size > MAX_ROLLBACK_VAULT_BYTES {
        return Err("rollback vault has an invalid size".into());
    }

    // Important: load_snapshot() would create a database on a missing path.
    // Rollback checks MUST open existing databases in read-only mode only.
    let rollback = Connection::open_with_flags(vault_path, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let integrity: String = rollback.query_row("PRAGMA integrity_check", [], |row| row.get(0))?;
    if integrity != "ok" {
        return Err("rollback vault failed SQLite integrity validation".into());
    }
    let saved: String = rollback.query_row(
        "SELECT payload FROM android_snapshot WHERE id=1",
        [],
        |row| row.get(0),
    )?;
    if normalized_snapshot(&saved)? != normalized_snapshot(current_raw)? {
        return Err("current legacy tasks differ from the independently saved rollback".into());
    }

    match audit_legacy_shadow(candidate_path, current_raw)? {
        ShadowAudit::Verified {
            current_matches: true,
            ..
        } => Ok(()),
        ShadowAudit::Verified {
            current_matches: false,
            ..
        } => Err("legacy source changed since the canonical cutover staging".into()),
        ShadowAudit::Missing => Err("native cutover candidate no longer exists".into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{parity::preflight, store_snapshot};
    use chrono::Utc;
    use serde_json::{Value, json};

    fn paths() -> (std::path::PathBuf, std::path::PathBuf) {
        let stamp = format!(
            "{}-{}",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        );
        let parent = std::env::temp_dir();
        (
            parent.join(format!("shiori-rollback-vault-{stamp}.sqlite3")),
            parent.join(format!("shiori-rollback-candidate-{stamp}.sqlite3")),
        )
    }

    fn source() -> String {
        json!({
            "format":"shiori-android-local-v1",
            "exported_at":"2026-11-13T10:45:00Z",
            "sort":"due",
            "saved_views":[{"name":"Next","view":"inbox",
                "filter":"high","sort":"due","query":"important"}],
            "tasks":[{"id":"android-001","title":"Keep original task",
                "description":"Unchanged task notes","project":"Home",
                "status":"progress","priority":"high","due":"2026-11-22",
                "tags":["Household","Offline"],"mins":30,"version":3,
                "createdAt":"2026-11-12T08:00:00Z",
                "updatedAt":"2026-11-13T08:00:00Z"}]
        })
        .to_string()
    }

    #[test]
    fn verifies_independent_backup_and_ignores_only_new_export_timestamp() {
        let (vault, candidate) = paths();
        let original = source();
        assert_eq!(preflight(&candidate, &original).unwrap()["ready"], true);
        store_snapshot(&vault, &original).unwrap();
        let mut later: Value = serde_json::from_str(&original).unwrap();
        later["exported_at"] = json!("2026-11-13T11:00:00Z");
        verify_legacy_rollback(&vault, &candidate, &later.to_string()).unwrap();
        assert_eq!(crate::load_snapshot(&vault).unwrap(), Some(original));
        fs::remove_file(vault).unwrap();
        fs::remove_file(candidate).unwrap();
    }

    #[test]
    fn refuses_missing_or_corrupt_vault_without_creating_missing_files() {
        let (vault, candidate) = paths();
        assert!(verify_legacy_rollback(&vault, &candidate, &source()).is_err());
        assert!(!vault.exists());
        assert!(!candidate.exists());

        let original = source();
        assert_eq!(preflight(&candidate, &original).unwrap()["ready"], true);
        fs::write(&vault, b"not SQLite").unwrap();
        assert!(verify_legacy_rollback(&vault, &candidate, &original).is_err());
        assert_eq!(fs::read(&vault).unwrap(), b"not SQLite");
        fs::remove_file(vault).unwrap();
        fs::remove_file(candidate).unwrap();
    }

    #[test]
    fn refuses_changed_task_tags_and_views_but_leaves_saved_records_intact() {
        let (vault, candidate) = paths();
        let original = source();
        assert_eq!(preflight(&candidate, &original).unwrap()["ready"], true);
        store_snapshot(&vault, &original).unwrap();
        for (key, value) in [
            ("title", "Changed after migration"),
            ("description", "Unexpected changes"),
        ] {
            let mut changed: Value = serde_json::from_str(&original).unwrap();
            changed["tasks"][0][key] = json!(value);
            assert!(verify_legacy_rollback(&vault, &candidate, &changed.to_string()).is_err());
        }
        let mut changed: Value = serde_json::from_str(&original).unwrap();
        changed["tasks"][0]["tags"][0] = json!("Different");
        assert!(verify_legacy_rollback(&vault, &candidate, &changed.to_string()).is_err());
        changed = serde_json::from_str(&original).unwrap();
        changed["saved_views"][0]["query"] = json!("another filter");
        assert!(verify_legacy_rollback(&vault, &candidate, &changed.to_string()).is_err());

        // A once-valid vault must not be treated as sufficient when the
        // canonical candidate itself has changed or is corrupted.
        let db = Connection::open(&candidate).unwrap();
        db.execute(
            "UPDATE android_task_tags SET value='tampered' WHERE position=0",
            [],
        )
        .unwrap();
        drop(db);
        assert!(verify_legacy_rollback(&vault, &candidate, &original).is_err());
        assert_eq!(crate::load_snapshot(&vault).unwrap(), Some(original));
        fs::remove_file(vault).unwrap();
        fs::remove_file(candidate).unwrap();
    }
}
