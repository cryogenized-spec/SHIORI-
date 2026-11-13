//! M2.4b: strictly read-only assessment of interrupted native cutover
//! artefacts. This module never changes source selection, creates SQLite
//! files, removes partial files, or promotes a primary database.
use rusqlite::{Connection, OpenFlags};
use serde_json::{Value, json};
use std::{error::Error, fs, path::Path};

use crate::{
    audit::normalized_snapshot, export::read_manifest, migration::read_android_metadata,
    parity::preflight, recovery::records_match, rollback::verify_legacy_rollback,
    validate_snapshot,
};

const MAX_PRIMARY_BYTES: u64 = 64 * 1024 * 1024;

/// A rollback-ready primary must be identical to the staged canonical
/// migration. In particular, a primary modified during an earlier canary
/// session is **not** automatically safe to resume after rollback.
fn verify_unselected_primary(
    candidate: &Path,
    primary: &Path,
    current_raw: &str,
) -> Result<(), Box<dyn Error>> {
    let bytes = fs::metadata(primary)?.len();
    if bytes == 0 || bytes > MAX_PRIMARY_BYTES {
        return Err("native primary has an invalid size".into());
    }
    let original = Connection::open_with_flags(candidate, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let staged = Connection::open_with_flags(primary, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
    let (archive, count, tombstones, dependencies) = read_manifest(&original)?;
    let (other, staged_count, staged_tombstones, staged_dependencies) = read_manifest(&staged)?;

    if normalized_snapshot(&archive)? != normalized_snapshot(current_raw)?
        || normalized_snapshot(&other)? != normalized_snapshot(current_raw)?
        || (count, tombstones, dependencies)
            != (staged_count, staged_tombstones, staged_dependencies)
        || !records_match(&original, &staged)?
        || read_android_metadata(candidate)? != read_android_metadata(primary)?
    {
        return Err("primary SQLite records differ from original migration".into());
    }
    for db in [&original, &staged] {
        let unexpected: i64 = db.query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger','view')",
            [],
            |row| row.get(0),
        )?;
        if unexpected != 0 {
            return Err("cutover source contains unsupported triggers or views".into());
        }
    }
    Ok(())
}

/// Examine an existing candidate, optional independent rollback vault and
/// optional primary. Return which *missing* steps are safely resumable.
///
/// Never call parity::preflight on a missing candidate, because that function
/// can stage a fresh DB. All inputs are app-private paths chosen by Kotlin;
/// a failure is terminal until the user chooses a non-destructive repair.
pub fn inspect_interrupted_stage(
    candidate: &Path,
    vault: &Path,
    primary: &Path,
    current_raw: &str,
) -> Result<Value, Box<dyn Error>> {
    validate_snapshot(current_raw)?;
    if !candidate.is_file() {
        return Err("no pre-existing canonical migration candidate to resume".into());
    }
    // Candidate preflight performs no writes when the path already exists.
    // It also rejects unmapped, future legacy fields.
    let report = preflight(candidate, current_raw)?;
    if report["ready"] != true {
        return Err("migration candidate is stale, incomplete or has unknown fields".into());
    }

    if vault.exists() {
        verify_legacy_rollback(vault, candidate, current_raw)?;
    }
    if primary.exists() {
        if !primary.is_file() {
            return Err("native primary path is not a regular file".into());
        }
        verify_unselected_primary(candidate, primary, current_raw)?;
    }
    Ok(json!({
        "ok": true,
        "ready": vault.is_file() && primary.is_file(),
        "needs_rollback_vault": !vault.exists(),
        "needs_native_primary": !primary.exists(),
        "task_records": report["task_records"],
        "source_matches": true,
        "original_sources_unchanged": true,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{export::export_working_database, store_snapshot};
    use chrono::Utc;
    use serde_json::json;

    fn paths() -> (std::path::PathBuf, std::path::PathBuf, std::path::PathBuf) {
        let suffix = format!(
            "{}-{}",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        );
        let root = std::env::temp_dir();
        (
            root.join(format!("shiori-resume-candidate-{suffix}.sqlite3")),
            root.join(format!("shiori-resume-rollback-{suffix}.sqlite3")),
            root.join(format!("shiori-resume-primary-{suffix}.sqlite3")),
        )
    }
    fn source() -> String {
        json!({
            "format":"shiori-android-local-v1",
            "exported_at":"2026-11-13T11:00:00Z",
            "sort":"fifo",
            "saved_views":[{"name":"Mine","view":"inbox",
                "filter":"all","sort":"fifo","query":""}],
            "tasks":[{
                "id":"legacy-42","title":"Repair invoice","description":"Don't lose 栞",
                "project":"Workshop","priority":"high","status":"progress",
                "tags":["Test","Native"],"due":"2026-11-14","mins":20,
                "createdAt":"2026-11-12T09:00:00Z",
                "updatedAt":"2026-11-13T10:00:00Z",
                "version":2,
                "assigneeId":"local"
            }]
        })
        .to_string()
    }

    #[test]
    fn only_a_preexisting_candidate_may_be_resumed_without_writes() {
        let (candidate, vault, primary) = paths();
        let original = source();
        assert!(inspect_interrupted_stage(&candidate, &vault, &primary, &original).is_err());
        assert!(!candidate.exists());
        assert!(!vault.exists());
        assert!(!primary.exists());
    }

    #[test]
    fn inspect_missing_vault_and_primary_then_require_both_independent_copies() {
        let (candidate, vault, primary) = paths();
        let original = source();
        assert_eq!(preflight(&candidate, &original).unwrap()["ready"], true);
        let report = inspect_interrupted_stage(&candidate, &vault, &primary, &original).unwrap();
        assert_eq!(report["ready"], false);
        assert_eq!(report["needs_rollback_vault"], true);
        assert_eq!(report["needs_native_primary"], true);
        store_snapshot(&vault, &original).unwrap();
        let partial = inspect_interrupted_stage(&candidate, &vault, &primary, &original).unwrap();
        assert_eq!(partial["needs_rollback_vault"], false);
        assert_eq!(partial["needs_native_primary"], true);
        export_working_database(&candidate, &primary).unwrap();
        let complete = inspect_interrupted_stage(&candidate, &vault, &primary, &original).unwrap();
        assert_eq!(complete["ready"], true);
        assert_eq!(complete["task_records"], 1);
        for file in [candidate, vault, primary] {
            fs::remove_file(file).unwrap();
        }
    }

    #[test]
    fn changed_primary_cannot_be_silently_promoted_again() {
        let (candidate, vault, primary) = paths();
        let original = source();
        preflight(&candidate, &original).unwrap();
        store_snapshot(&vault, &original).unwrap();
        export_working_database(&candidate, &primary).unwrap();
        let db = Connection::open(&primary).unwrap();
        db.execute(
            "UPDATE tasks SET title='Edited while native was active' WHERE id='legacy-42'",
            [],
        )
        .unwrap();
        drop(db);
        assert!(inspect_interrupted_stage(&candidate, &vault, &primary, &original).is_err());
        assert!(primary.is_file());
        assert!(vault.is_file());
        for file in [candidate, vault, primary] {
            fs::remove_file(file).unwrap();
        }
    }

    #[test]
    fn stale_or_corrupt_artifacts_are_never_replaced_while_inspecting() {
        let (candidate, vault, primary) = paths();
        let original = source();
        preflight(&candidate, &original).unwrap();
        fs::write(&vault, b"Existing old vault").unwrap();
        assert!(inspect_interrupted_stage(&candidate, &vault, &primary, &original).is_err());
        assert_eq!(fs::read(&vault).unwrap(), b"Existing old vault");
        fs::remove_file(&vault).unwrap();
        let mut changed: Value = serde_json::from_str(&original).unwrap();
        changed["tasks"][0]["title"] = json!("Different tasks");
        assert!(
            inspect_interrupted_stage(&candidate, &vault, &primary, &changed.to_string()).is_err()
        );
        assert!(!primary.exists());
        fs::remove_file(candidate).unwrap();
    }
}
