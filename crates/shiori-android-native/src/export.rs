//! Crash-consistent export of the *separate experimental* native task DB.
//! Export-only: never overwrite, import, or promote the live WebView store.
//! SQLite VACUUM INTO produces a consistent single-file copy even in WAL mode.
use rusqlite::{Connection, OpenFlags, params};
use std::{error::Error, fs, path::Path};

const MAX_EXPORT_BYTES: u64 = 64 * 1024 * 1024;
const CANONICAL_SCHEMA: i64 = 3;

#[derive(Debug)]
pub struct ExportReport {
    pub records: i64,
    pub tombstones: i64,
    pub dependencies: i64,
    pub bytes: u64,
}

fn read_manifest(db: &Connection) -> Result<(String, i64, i64, i64), Box<dyn Error>> {
    let integrity: String = db.query_row("PRAGMA quick_check", [], |row| row.get(0))?;
    if integrity != "ok" {
        return Err("SQLite integrity check failed".into());
    }
    let version: i64 = db.pragma_query_value(None, "user_version", |row| row.get(0))?;
    if version != CANONICAL_SCHEMA {
        return Err("unsupported canonical working database schema".into());
    }
    // The archived legacy JSON sidecar distinguishes the experimental
    // working copy from an unrelated SQLite file with a similar schema.
    let archive: String = db.query_row(
        "SELECT payload FROM legacy_shadow_source WHERE id=1",
        [],
        |row| row.get(0),
    )?;
    crate::validate_snapshot(&archive)?;
    let records: i64 = db.query_row("SELECT COUNT(*) FROM tasks", [], |row| row.get(0))?;
    let tombstones: i64 = db.query_row(
        "SELECT COUNT(*) FROM tasks WHERE deleted_at IS NOT NULL",
        [],
        |row| row.get(0),
    )?;
    let dependencies: i64 = db.query_row(
        "SELECT COUNT(*) FROM task_dependencies",
        [],
        |row| row.get(0),
    )?;
    Ok((archive, records, tombstones, dependencies))
}

/// Create a verified, independent SQLite archive at a NEW app-private path.
/// The Android Activity later streams these bytes through an explicit SAF
/// ACTION_CREATE_DOCUMENT picker. This function never writes to source.
/// On failed export/verification, a newly created partial target is removed.
pub fn export_working_database(
    source: &Path,
    target: &Path,
) -> Result<ExportReport, Box<dyn Error>> {
    if !source.is_file() {
        return Err("no native working database is available".into());
    }
    if target.exists() || source == target {
        return Err("export destination must be a new, separate file".into());
    }

    let result = (|| -> Result<ExportReport, Box<dyn Error>> {
        let db = Connection::open_with_flags(source, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        let manifest = read_manifest(&db)?;
        // VACUUM INTO is a SQLite-level snapshot operation, not a raw copy
        // of an open .sqlite3 / -wal pair. It is safe for an active WAL DB.
        db.execute("VACUUM INTO ?1", params![target.to_string_lossy().as_ref()])?;
        drop(db);
        let bytes = fs::metadata(target)?.len();
        if bytes == 0 || bytes > MAX_EXPORT_BYTES {
            return Err("native working export exceeds the 64 MB safety limit".into());
        }
        let exported = Connection::open_with_flags(target, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        let copied = read_manifest(&exported)?;
        if copied != manifest {
            return Err("exported database did not match the source manifest".into());
        }
        Ok(ExportReport {
            records: copied.1,
            tombstones: copied.2,
            dependencies: copied.3,
            bytes,
        })
    })();
    if result.is_err() {
        // Destination did not exist before our operation. Never remove any
        // pre-existing file; that case was rejected before entering here.
        let _ = fs::remove_file(target);
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::working_copy::initialize_working_copy;
    use chrono::Utc;
    use shiori_core::{Priority, Task};
    use shiori_storage::SqliteStore;

    fn paths() -> (std::path::PathBuf, std::path::PathBuf) {
        let suffix = format!(
            "{}-{}", std::process::id(), Utc::now().timestamp_nanos_opt().unwrap()
        );
        let dir = std::env::temp_dir();
        (
            dir.join(format!("shiori-export-{suffix}.sqlite3")),
            dir.join(format!("shiori-export-{suffix}.backup.sqlite3")),
        )
    }
    fn backup() -> String {
        serde_json::json!({
            "format":"shiori-android-local-v1",
            "exported_at":"2026-11-13T09:00:00Z",
            "tasks":[{"id":"legacy-1","title":"Legacy task","project":"Personal",
                "description":"Preserved", "priority":"medium","status":"todo",
                "due":"","tags":["original"]}],
            "saved_views":[], "sort":"fifo"
        })
        .to_string()
    }

    #[test]
    fn exports_active_wal_with_dependencies_tombstones_and_archived_source() {
        let (source, target) = paths();
        let original = backup();
        initialize_working_copy(&source, &original).unwrap();
        {
            let connection = Connection::open(&source).unwrap();
            let journal: String = connection
                .query_row("PRAGMA journal_mode=WAL", [], |r| r.get(0))
                .unwrap();
            assert_eq!(journal.to_lowercase(), "wal");
        }
        let new_id;
        {
            let mut store = SqliteStore::open(&source).unwrap();
            let base = Task::new("Native base", "Personal", Priority::High, None).unwrap();
            let child = Task::new("Native dependent", "Personal", Priority::Low, None).unwrap();
            let tombstone = Task::new("Deleted native", "Personal", Priority::Low, None).unwrap();
            store.insert(&base).unwrap();
            store.insert(&child).unwrap();
            store.insert(&tombstone).unwrap();
            store.set_dependencies(&child.id, &[base.id]).unwrap();
            store.delete(&tombstone.id).unwrap();
            new_id = child.id.clone();
        }
        let report = export_working_database(&source, &target).unwrap();
        assert_eq!(report.records, 4);
        assert_eq!(report.tombstones, 1);
        assert_eq!(report.dependencies, 1);
        assert!(report.bytes > 0);
        assert_eq!(report.bytes, fs::metadata(&target).unwrap().len());
        let copied = Connection::open_with_flags(&target, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
        let (archived, records, deleted, edges) = read_manifest(&copied).unwrap();
        assert_eq!(archived, original);
        assert_eq!((records, deleted, edges), (4, 1, 1));
        let title: String = copied
            .query_row("SELECT title FROM tasks WHERE id=?1", params![new_id], |row| row.get(0))
            .unwrap();
        assert_eq!(title, "Native dependent");
        drop(copied);
        assert!(export_working_database(&source, &target).is_err());
        assert_eq!(fs::metadata(&target).unwrap().len(), report.bytes);
        assert_eq!(
            SqliteStore::open(&source).unwrap().legacy_shadow_source().unwrap(),
            Some(original)
        );
        fs::remove_file(target).unwrap();
        fs::remove_file(source).unwrap();
    }

    #[test]
    fn invalid_sources_and_existing_destinations_fail_without_touching_files() {
        let (source, target) = paths();
        assert!(export_working_database(&source, &target).is_err());
        assert!(!target.exists());
        fs::write(&source, b"not a sqlite database").unwrap();
        assert!(export_working_database(&source, &target).is_err());
        assert!(!target.exists());
        fs::write(&target, b"keep existing bytes").unwrap();
        assert!(export_working_database(&source, &target).is_err());
        assert_eq!(fs::read(&target).unwrap(), b"keep existing bytes");
        fs::remove_file(source).unwrap();
        fs::remove_file(target).unwrap();
    }
}
