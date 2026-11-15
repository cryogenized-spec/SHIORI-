//! Isolated SQLite view store for ISW coordinates and read-only task edges.
//! This sidecar must never change the canonical task database schema/version.
use crate::{SqliteStore, StorageError};
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use shiori_core::spatial::{
    SpatialError, SpatialPosition, validate_coordinates, validate_view_revision,
};
use std::path::Path;

const VIEW_SCHEMA_VERSION: i64 = 1;

pub struct SpatialViewStore {
    db: Connection,
}

impl SpatialViewStore {
    /// Open a dedicated layout database, for example tasks.isw.sqlite3.
    /// This is not the canonical tasks.sqlite3 and must not be treated as one.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, StorageError> {
        Self::initialize(Connection::open(path)?)
    }

    pub fn in_memory() -> Result<Self, StorageError> {
        Self::initialize(Connection::open_in_memory()?)
    }

    fn initialize(mut db: Connection) -> Result<Self, StorageError> {
        db.execute_batch("PRAGMA busy_timeout = 4000;")?;
        let version: i64 = db.pragma_query_value(None, "user_version", |row| row.get(0))?;
        if version != 0 && version != VIEW_SCHEMA_VERSION {
            return Err(StorageError::UnsupportedSpatialSchemaVersion {
                found: version,
                supported: VIEW_SCHEMA_VERSION,
            });
        }
        if version == 0 {
            let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
            let existing: i64 = tx.query_row(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='isw_positions'",
                [],
                |row| row.get(0),
            )?;
            if existing != 0 {
                return Err(StorageError::InvalidSpatialSchema);
            }
            tx.execute_batch(
                "CREATE TABLE isw_positions (
                   task_id TEXT PRIMARY KEY,
                   x REAL NOT NULL CHECK(x BETWEEN -1000000 AND 1000000),
                   y REAL NOT NULL CHECK(y BETWEEN -1000000 AND 1000000),
                   revision INTEGER NOT NULL CHECK(revision > 0)
                 );",
            )?;
            tx.pragma_update(None, "user_version", VIEW_SCHEMA_VERSION)?;
            tx.commit()?;
        } else {
            let columns: Vec<String> = {
                let mut stmt = db.prepare("PRAGMA table_info(isw_positions)")?;
                let values = stmt.query_map([], |row| row.get(1))?;
                values.collect::<rusqlite::Result<Vec<_>>>()?
            };
            if columns != ["task_id", "x", "y", "revision"] {
                return Err(StorageError::InvalidSpatialSchema);
            }
        }
        Ok(Self { db })
    }

    pub fn positions(&self) -> Result<Vec<SpatialPosition>, StorageError> {
        let mut stmt = self
            .db
            .prepare("SELECT task_id,x,y,revision FROM isw_positions ORDER BY task_id")?;
        let values = stmt.query_map([], |row| {
            Ok(SpatialPosition {
                task_id: row.get(0)?,
                x: row.get(1)?,
                y: row.get(2)?,
                revision: row.get(3)?,
            })
        })?;
        Ok(values.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Check the canonical record's existence and active status, then update
    /// ONLY the sidecar view database. Its own revision is independent of
    /// task versions and dependency graph edits.
    pub fn set_position(
        &mut self,
        tasks: &SqliteStore,
        task_id: &str,
        x: f64,
        y: f64,
        expected_revision: i64,
    ) -> Result<SpatialPosition, StorageError> {
        validate_coordinates(x, y)?;
        validate_view_revision(expected_revision)?;
        tasks.get(task_id)?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let old: Option<(f64, f64, i64)> = tx
            .query_row(
                "SELECT x,y,revision FROM isw_positions WHERE task_id=?1",
                params![task_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .optional()?;
        let current = old.as_ref().map_or(0, |v| v.2);
        if expected_revision != current {
            return Err(StorageError::RevisionConflict);
        }
        if let Some((old_x, old_y, _)) = old {
            if old_x != x || old_y != y {
                tx.execute(
                    "UPDATE isw_positions SET x=?2,y=?3,revision=revision+1 WHERE task_id=?1",
                    params![task_id, x, y],
                )?;
            }
        } else {
            tx.execute(
                "INSERT INTO isw_positions(task_id,x,y,revision) VALUES(?1,?2,?3,1)",
                params![task_id, x, y],
            )?;
        }
        let result = tx.query_row(
            "SELECT task_id,x,y,revision FROM isw_positions WHERE task_id=?1",
            params![task_id],
            |row| {
                Ok(SpatialPosition {
                    task_id: row.get(0)?,
                    x: row.get(1)?,
                    y: row.get(2)?,
                    revision: row.get(3)?,
                })
            },
        )?;
        tx.commit()?;
        Ok(result)
    }
}

impl SqliteStore {
    /// Verified source -> dependent IDs from the canonical task prerequisites.
    pub fn spatial_dependency_edges(&self) -> Result<Vec<(String, String)>, StorageError> {
        let mut stmt = self.db.prepare(
            "SELECT dep.depends_on_id, dep.task_id
             FROM task_dependencies dep
             JOIN tasks prerequisite ON prerequisite.id = dep.depends_on_id
             JOIN tasks dependent ON dependent.id = dep.task_id
             WHERE prerequisite.deleted_at IS NULL AND dependent.deleted_at IS NULL
             ORDER BY dep.depends_on_id, dep.task_id",
        )?;
        let values = stmt.query_map([], |row| Ok((row.get(0)?, row.get(1)?)))?;
        Ok(values.collect::<rusqlite::Result<Vec<_>>>()?)
    }
}

impl From<SpatialError> for StorageError {
    fn from(value: SpatialError) -> Self {
        Self::Spatial(value)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use shiori_core::{Priority, Task};

    #[test]
    fn sidecar_positions_are_versioned_and_do_not_modify_task_revisions() {
        let tasks = SqliteStore::in_memory().unwrap();
        let mut view = SpatialViewStore::in_memory().unwrap();
        let task = Task::new("Visual position", "Workshop", Priority::Low, None).unwrap();
        tasks.insert(&task).unwrap();
        let a = view.set_position(&tasks, &task.id, 100., 200., 0).unwrap();
        assert_eq!(a.revision, 1);
        let b = view.set_position(&tasks, &task.id, 100., 200., 1).unwrap();
        assert_eq!(b.revision, 1);
        let c = view.set_position(&tasks, &task.id, 125., 200., 1).unwrap();
        assert_eq!(c.revision, 2);
        assert!(matches!(
            view.set_position(&tasks, &task.id, 300., 300., 1),
            Err(StorageError::RevisionConflict)
        ));
        assert_eq!(tasks.get(&task.id).unwrap().version, task.version);
        assert_eq!(view.positions().unwrap().len(), 1);
    }

    #[test]
    fn view_does_not_store_invalid_or_unknown_task_coordinates() {
        let tasks = SqliteStore::in_memory().unwrap();
        let mut view = SpatialViewStore::in_memory().unwrap();
        assert!(matches!(
            view.set_position(&tasks, "missing", 1., 2., 0),
            Err(StorageError::NotFound)
        ));
        let task = Task::new("Task", "Workshop", Priority::Medium, None).unwrap();
        tasks.insert(&task).unwrap();
        assert!(matches!(
            view.set_position(&tasks, &task.id, f64::NAN, 2., 0),
            Err(StorageError::Spatial(_))
        ));
        assert!(view.positions().unwrap().is_empty());
    }

    #[test]
    fn canonical_dependency_edges_are_distinct_from_view_state() {
        let mut tasks = SqliteStore::in_memory().unwrap();
        let a = Task::new("A", "Ops", Priority::Low, None).unwrap();
        let b = Task::new("B", "Ops", Priority::Low, None).unwrap();
        tasks.insert(&a).unwrap();
        tasks.insert(&b).unwrap();
        tasks
            .set_dependencies(&b.id, std::slice::from_ref(&a.id))
            .unwrap();
        assert_eq!(
            tasks.spatial_dependency_edges().unwrap(),
            vec![(a.id, b.id)]
        );
    }

    #[test]
    fn rejects_unknown_sidecar_schema_versions() {
        let view = SpatialViewStore::in_memory().unwrap();
        view.db.pragma_update(None, "user_version", 22_i64).unwrap();
        drop(view);
        // View schema validation is intentionally independent of canonical DB.
        let temp = tempfile::tempdir().unwrap();
        let path = temp.path().join("positions.sqlite3");
        let db = Connection::open(&path).unwrap();
        db.pragma_update(None, "user_version", 22_i64).unwrap();
        assert!(matches!(
            SpatialViewStore::open(&path),
            Err(StorageError::UnsupportedSpatialSchemaVersion { found: 22, .. })
        ));
    }
}
