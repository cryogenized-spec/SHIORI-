//! SQLite adapter for view-only ISW coordinates and canonical task links.
//! The authoritative task state remains in the existing tasks/dependencies tables.
use crate::{SqliteStore, StorageError};
use rusqlite::{OptionalExtension, TransactionBehavior, params};
use shiori_core::spatial::{
    SpatialError, SpatialPosition, validate_coordinates, validate_view_revision,
};

impl SqliteStore {
    /// Source -> dependent task, derived from real task prerequisites.
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

    /// View positions for active tasks only. There is no task mutation.
    pub fn spatial_positions(&self) -> Result<Vec<SpatialPosition>, StorageError> {
        let mut stmt = self.db.prepare(
            "SELECT p.task_id,p.x,p.y,p.revision FROM isw_positions p
             JOIN tasks t ON t.id=p.task_id WHERE t.deleted_at IS NULL
             ORDER BY p.task_id",
        )?;
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

    /// Optimistic revision on the spatial view, never a task revision.
    /// A new position requires expected_revision=0; retries with same
    /// coordinates are idempotent only when the expected revision matches
    /// the current record.
    pub fn set_spatial_position(
        &mut self,
        task_id: &str,
        x: f64,
        y: f64,
        expected_revision: i64,
    ) -> Result<SpatialPosition, StorageError> {
        validate_coordinates(x, y)?;
        validate_view_revision(expected_revision)?;
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let active: i64 = tx.query_row(
            "SELECT COUNT(*) FROM tasks WHERE id=?1 AND deleted_at IS NULL",
            params![task_id],
            |row| row.get(0),
        )?;
        if active == 0 {
            return Err(StorageError::NotFound);
        }
        let old: Option<(f64, f64, i64)> = tx
            .query_row(
                "SELECT x,y,revision FROM isw_positions WHERE task_id=?1",
                params![task_id],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .optional()?;
        let current = old.as_ref().map_or(0, |x| x.2);
        if expected_revision != current {
            return Err(StorageError::RevisionConflict);
        }
        if let Some((ox, oy, _)) = old {
            if ox != x || oy != y {
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
    fn coordinates_do_not_change_task_and_are_versioned() {
        let mut store = SqliteStore::in_memory().unwrap();
        let task = Task::new("Visual position", "Workshop", Priority::Low, None).unwrap();
        store.insert(&task).unwrap();
        let a = store.set_spatial_position(&task.id, 100., 200., 0).unwrap();
        assert_eq!(a.revision, 1);
        let b = store.set_spatial_position(&task.id, 100., 200., 1).unwrap();
        assert_eq!(b.revision, 1);
        let c = store.set_spatial_position(&task.id, 125., 200., 1).unwrap();
        assert_eq!(c.revision, 2);
        assert!(matches!(
            store.set_spatial_position(&task.id, 300., 300., 1),
            Err(StorageError::RevisionConflict)
        ));
        assert_eq!(store.get(&task.id).unwrap().version, task.version);
        assert_eq!(store.spatial_positions().unwrap().len(), 1);
    }
    #[test]
    fn denies_unowned_positions_or_invalid_geometry() {
        let mut store = SqliteStore::in_memory().unwrap();
        assert!(matches!(
            store.set_spatial_position("missing", 1., 2., 0),
            Err(StorageError::NotFound)
        ));
        let task = Task::new("Task", "Workshop", Priority::Medium, None).unwrap();
        store.insert(&task).unwrap();
        assert!(matches!(
            store.set_spatial_position(&task.id, f64::NAN, 2., 0),
            Err(StorageError::Spatial(_))
        ));
        assert!(store.spatial_positions().unwrap().is_empty());
    }
    #[test]
    fn exposes_task_dependencies_without_inventing_links() {
        let mut store = SqliteStore::in_memory().unwrap();
        let a = Task::new("A", "Ops", Priority::Low, None).unwrap();
        let b = Task::new("B", "Ops", Priority::Low, None).unwrap();
        store.insert(&a).unwrap();
        store.insert(&b).unwrap();
        store.set_dependencies(&b.id, &[a.id.clone()]).unwrap();
        assert_eq!(
            store.spatial_dependency_edges().unwrap(),
            vec![(a.id, b.id)]
        );
    }
}
