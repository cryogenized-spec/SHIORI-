//! Opt-in import of a SHIORI *exported* SQLite database into a NEW,
//! non-authoritative recovery preview. Never open or overwrite the existing
//! editable working copy, migration shadow, WebView store, or safety vault.
use rusqlite::{Connection, OpenFlags, Row, params, types::Value};
use std::{error::Error, fs, path::Path};

use crate::export::read_manifest;

const MAX_RECOVERY_BYTES: u64 = 64 * 1024 * 1024;
const MAX_RECOVERY_RECORDS: i64 = 5_000;

#[derive(Debug)]
pub struct RecoveryReport {
    pub records: i64,
    pub tombstones: i64,
    pub dependencies: i64,
}

/// Full ordered row values, not merely counts: a recovery preview must
/// contain the same task fields, revisions, tombstones, dependencies and
/// legacy source archive as the supplied standalone SQLite backup.
fn table_rows(db: &Connection, sql: &str) -> Result<Vec<Vec<Value>>, Box<dyn Error>> {
    let mut statement = db.prepare(sql)?;
    let column_count = statement.column_count();
    let rows = statement.query_map([], |row: &Row<'_>| {
        (0..column_count)
            .map(|index| row.get::<_, Value>(index))
            .collect::<rusqlite::Result<Vec<_>>>()
    })?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

pub(crate) fn records_match(
    original: &Connection,
    recovered: &Connection,
) -> Result<bool, Box<dyn Error>> {
    // Comparing every canonical column catches differences that counts alone
    // miss, including status, revision and deleted_at differences.
    const TASKS: &str = "SELECT id,title,notes,project,priority,status,due_on,created_at,updated_at,completed_at,version,deleted_at,estimate_minutes,assignee_id FROM tasks ORDER BY id";
    const DEPENDENCIES: &str =
        "SELECT task_id,depends_on_id FROM task_dependencies ORDER BY task_id,depends_on_id";
    Ok(
        table_rows(original, TASKS)? == table_rows(recovered, TASKS)?
            && table_rows(original, DEPENDENCIES)? == table_rows(recovered, DEPENDENCIES)?,
    )
}

/// Restore an independently exported working-copy database as a distinct
/// recovery preview. Input is the bounded, private staging copy of a file
/// chosen via Android's ACTION_OPEN_DOCUMENT picker. Destination must NOT
/// exist; all other app databases remain untouched.
///
/// SQLite VACUUM INTO, instead of a raw file copy, normalizes standalone
/// input and writes a consistent new database. Validate both sides.
pub fn recover_to_separate_preview(
    source: &Path,
    destination: &Path,
) -> Result<RecoveryReport, Box<dyn Error>> {
    if !source.is_file() || destination.exists() || source == destination {
        return Err("recovery requires a readable source and a NEW separate destination".into());
    }
    let bytes = fs::metadata(source)?.len();
    if bytes == 0 || bytes > MAX_RECOVERY_BYTES {
        return Err("native SQLite backup is empty or exceeds 64 MB".into());
    }

    let attempt = (|| -> Result<RecoveryReport, Box<dyn Error>> {
        let original = Connection::open_with_flags(source, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        let before = read_manifest(&original)?;
        if before.1 > MAX_RECOVERY_RECORDS {
            return Err("recovery preview exceeds the 5000-task safety limit".into());
        }
        // Reject files with unexpected executable schema additions, e.g.
        // triggers or views. SHIORI's canonical schema does not use them.
        let forbidden: i64 = original.query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE type IN ('trigger','view')",
            [],
            |row| row.get(0),
        )?;
        if forbidden != 0 {
            return Err("backup contains unsupported SQLite triggers or views".into());
        }
        original.execute(
            "VACUUM INTO ?1",
            params![destination.to_string_lossy().as_ref()],
        )?;
        let restored_bytes = fs::metadata(destination)?.len();
        if restored_bytes == 0 || restored_bytes > MAX_RECOVERY_BYTES {
            return Err("recovered database exceeds the safety size limit".into());
        }

        let restored = Connection::open_with_flags(destination, OpenFlags::SQLITE_OPEN_READ_ONLY)?;
        let after = read_manifest(&restored)?;
        if before != after || !records_match(&original, &restored)? {
            return Err("recovered database differs from the selected backup".into());
        }
        Ok(RecoveryReport {
            records: after.1,
            tombstones: after.2,
            dependencies: after.3,
        })
    })();
    if attempt.is_err() {
        // Never remove a pre-existing path: this only runs after the
        // destination-exists guard. A failed, new preview is expendable.
        let _ = fs::remove_file(destination);
    }
    attempt
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::{export::export_working_database, working_copy::initialize_working_copy};
    use chrono::Utc;
    use shiori_core::{Priority, Task};
    use shiori_storage::SqliteStore;

    fn locations() -> (std::path::PathBuf, std::path::PathBuf, std::path::PathBuf) {
        let stamp = format!(
            "{}-{}",
            std::process::id(),
            Utc::now().timestamp_nanos_opt().unwrap()
        );
        let root = std::env::temp_dir();
        (
            root.join(format!("shiori-recovery-original-{stamp}.sqlite3")),
            root.join(format!("shiori-recovery-backup-{stamp}.sqlite3")),
            root.join(format!("shiori-recovery-isolated-{stamp}.sqlite3")),
        )
    }
    fn backup() -> String {
        serde_json::json!({
            "format":"shiori-android-local-v1",
            "exported_at":"2026-11-13T09:00:00Z",
            "tasks":[{
                "id":"old-task", "title":"Imported legacy 栞","project":"Personal",
                "description":"Original description", "priority":"high",
                "status":"todo", "due":"", "tags":["old"]
            }],
            "saved_views":[], "sort":"fifo"
        })
        .to_string()
    }

    #[test]
    fn restores_export_into_isolated_preview_with_all_records_and_history() {
        let (source, archive, isolated) = locations();
        let original = backup();
        initialize_working_copy(&source, &original).unwrap();
        let (active_id, deleted_id);
        {
            let mut store = SqliteStore::open(&source).unwrap();
            let active = Task::new("Native active", "Personal", Priority::Medium, None).unwrap();
            let deleted = Task::new("Deleted record", "Personal", Priority::Low, None).unwrap();
            let prerequisite = Task::new("Dependency", "Personal", Priority::High, None).unwrap();
            active_id = active.id.clone();
            deleted_id = deleted.id.clone();
            store.insert(&active).unwrap();
            store.insert(&deleted).unwrap();
            store.insert(&prerequisite).unwrap();
            store
                .set_dependencies(&active_id, &[prerequisite.id])
                .unwrap();
            store.delete(&deleted_id).unwrap();
        }
        export_working_database(&source, &archive).unwrap();
        let restored = recover_to_separate_preview(&archive, &isolated).unwrap();
        assert_eq!(restored.records, 4);
        assert_eq!(restored.tombstones, 1);
        assert_eq!(restored.dependencies, 1);
        let original_db =
            Connection::open_with_flags(&source, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
        let restored_db =
            Connection::open_with_flags(&isolated, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
        assert!(records_match(&original_db, &restored_db).unwrap());
        assert_eq!(read_manifest(&restored_db).unwrap().0, original);
        assert!(fs::metadata(&archive).unwrap().len() > 0);
        drop(restored_db);
        drop(original_db);
        // Re-import cannot silently replace previously recovered edits.
        assert!(recover_to_separate_preview(&archive, &isolated).is_err());
        let check =
            Connection::open_with_flags(&isolated, OpenFlags::SQLITE_OPEN_READ_ONLY).unwrap();
        assert_eq!(
            table_rows(&check, "SELECT id FROM tasks ORDER BY id")
                .unwrap()
                .len(),
            4
        );
        drop(check);
        for path in [source, archive, isolated] {
            fs::remove_file(path).unwrap();
        }
    }

    #[test]
    fn rejects_bad_backup_schema_corruption_and_existing_destination() {
        let (source, archive, isolated) = locations();
        fs::write(&source, b"not a SQLite database").unwrap();
        assert!(recover_to_separate_preview(&source, &isolated).is_err());
        assert!(!isolated.exists());
        let conn = Connection::open(&archive).unwrap();
        conn.execute_batch("PRAGMA user_version=99; CREATE TABLE fake (x TEXT);")
            .unwrap();
        drop(conn);
        assert!(recover_to_separate_preview(&archive, &isolated).is_err());
        assert!(!isolated.exists());
        fs::write(&isolated, b"Keep this previous recovery").unwrap();
        assert!(recover_to_separate_preview(&archive, &isolated).is_err());
        assert_eq!(fs::read(&isolated).unwrap(), b"Keep this previous recovery");
        for path in [source, archive, isolated] {
            fs::remove_file(path).unwrap();
        }
    }

    #[test]
    fn rejects_invalid_foreign_keys_and_unexpected_schema_objects() {
        let (source, archive, isolated) = locations();
        initialize_working_copy(&source, &backup()).unwrap();
        export_working_database(&source, &archive).unwrap();
        {
            let db = Connection::open(&archive).unwrap();
            db.execute_batch(
                "PRAGMA foreign_keys=OFF;
                 INSERT INTO task_dependencies(task_id,depends_on_id)
                 VALUES ('old-task','missing-prerequisite');",
            )
            .unwrap();
        }
        assert!(recover_to_separate_preview(&archive, &isolated).is_err());
        assert!(!isolated.exists());
        fs::remove_file(&archive).unwrap();
        export_working_database(&source, &archive).unwrap();
        {
            let db = Connection::open(&archive).unwrap();
            db.execute_batch(
                "CREATE TRIGGER unexpected AFTER INSERT ON tasks BEGIN SELECT 1; END;",
            )
            .unwrap();
        }
        assert!(recover_to_separate_preview(&archive, &isolated).is_err());
        assert!(!isolated.exists());
        for path in [source, archive] {
            fs::remove_file(path).unwrap();
        }
    }
}
