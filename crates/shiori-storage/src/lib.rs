//! SQLite persistence adapter. Domain validation stays in `shiori-core`.
use chrono::{DateTime, NaiveDate, Utc};
use rusqlite::{
    Connection, OptionalExtension, Row, TransactionBehavior, params, params_from_iter,
    types::{Type, Value},
};
use shiori_core::{Priority, Task, TaskError, TaskPatch, TaskStatus};
use std::{path::Path, str::FromStr};
use thiserror::Error;

const SCHEMA_VERSION: i64 = 2;

const SELECT: &str = "SELECT id, title, notes, project, priority, status, due_on, created_at, updated_at, completed_at, version, deleted_at, estimate_minutes FROM tasks";

#[derive(Debug, Error)]
pub enum StorageError {
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Domain(#[from] TaskError),
    #[error("task not found")]
    NotFound,
    #[error("task was changed by another writer")]
    RevisionConflict,
    #[error("unsupported SQLite schema version {found} (latest supported: {supported})")]
    UnsupportedSchemaVersion { found: i64, supported: i64 },
    #[error("unversioned SQLite database has an incompatible task schema")]
    IncompatibleLegacySchema,
    #[error("dependency must reference a different, active task")]
    InvalidDependency,
    #[error("dependency is missing or deleted: {0}")]
    MissingDependency(String),
    #[error("duplicate dependency ID")]
    DuplicateDependency,
    #[error("this prerequisite would create a task cycle")]
    DependencyCycle,
}

#[derive(Default)]
pub struct TaskFilter<'a> {
    pub project: Option<&'a str>,
    pub status: Option<TaskStatus>,
    pub due_on_or_before: Option<NaiveDate>,
    pub search: Option<&'a str>,
    pub include_deleted: bool,
}

pub struct SqliteStore {
    db: Connection,
}

impl SqliteStore {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, StorageError> {
        let db = Connection::open(path)?;
        Self::initialize(db)
    }

    pub fn in_memory() -> Result<Self, StorageError> {
        Self::initialize(Connection::open_in_memory()?)
    }

    fn initialize(mut db: Connection) -> Result<Self, StorageError> {
        db.execute_batch("PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 4000;")?;
        let version: i64 = db.pragma_query_value(None, "user_version", |row| row.get(0))?;
        if version != 0 && version != 1 && version != SCHEMA_VERSION {
            return Err(StorageError::UnsupportedSchemaVersion {
                found: version,
                supported: SCHEMA_VERSION,
            });
        }
        if version == 0 {
            // The initial unversioned schema is our v0 legacy fixture. Upgrade
            // in one IMMEDIATE transaction; an interrupted upgrade rolls back.
            let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
            tx.execute_batch(
                r#"
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                project TEXT NOT NULL,
                priority TEXT NOT NULL CHECK(priority IN ('low', 'medium', 'high', 'urgent')),
                status TEXT NOT NULL CHECK(status IN ('todo', 'in_progress', 'done')),
                due_on TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                version INTEGER NOT NULL CHECK(version > 0),
                deleted_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_active_due ON tasks(deleted_at, due_on, status);
            CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at);
        "#,
            )?;
            let columns = {
                let mut stmt = tx.prepare("PRAGMA table_info(tasks)")?;
                let rows = stmt.query_map([], |row| row.get::<_, String>(1))?;
                rows.collect::<rusqlite::Result<Vec<_>>>()?
            };
            let expected = [
                "id",
                "title",
                "notes",
                "project",
                "priority",
                "status",
                "due_on",
                "created_at",
                "updated_at",
                "completed_at",
                "version",
                "deleted_at",
            ];
            if !columns
                .iter()
                .map(String::as_str)
                .eq(expected.iter().copied())
            {
                return Err(StorageError::IncompatibleLegacySchema);
            }
            tx.pragma_update(None, "user_version", 1_i64)?;
            tx.commit()?;
        }
        if version < 2 {
            // A separate atomic migration from the stable v1 schema. A crash
            // between v0->v1 and v1->v2 can safely resume next time.
            let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
            tx.execute_batch(
                "ALTER TABLE tasks ADD COLUMN estimate_minutes INTEGER
                    CHECK (estimate_minutes IS NULL OR (estimate_minutes BETWEEN 1 AND 1440));
                 CREATE TABLE task_dependencies (
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    depends_on_id TEXT NOT NULL REFERENCES tasks(id),
                    PRIMARY KEY (task_id, depends_on_id),
                    CHECK (task_id <> depends_on_id)
                 );
                 CREATE INDEX idx_task_dependencies_prerequisite
                    ON task_dependencies(depends_on_id);",
            )?;
            tx.pragma_update(None, "user_version", SCHEMA_VERSION)?;
            tx.commit()?;
        }
        Ok(Self { db })
    }

    pub fn insert(&self, task: &Task) -> Result<(), StorageError> {
        self.db.execute(
            "INSERT INTO tasks(id,title,notes,project,priority,status,due_on,created_at,updated_at,completed_at,version,deleted_at,estimate_minutes) VALUES (?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13)",
            params![task.id, task.title, task.notes, task.project, task.priority.as_str(), task.status.as_str(), task.due_on.map(|d| d.to_string()), task.created_at.to_rfc3339(), task.updated_at.to_rfc3339(), task.completed_at.map(|t| t.to_rfc3339()), task.version, task.deleted_at.map(|t| t.to_rfc3339()), task.estimate_minutes]
        )?;
        Ok(())
    }

    pub fn get(&self, id: &str) -> Result<Task, StorageError> {
        self.db
            .query_row(
                &format!("{SELECT} WHERE id=?1 AND deleted_at IS NULL"),
                params![id],
                task_from_row,
            )
            .optional()?
            .ok_or(StorageError::NotFound)
    }

    pub fn list(&self, filter: TaskFilter<'_>) -> Result<Vec<Task>, StorageError> {
        let mut sql = format!("{SELECT} WHERE 1=1");
        let mut args: Vec<Value> = Vec::new();
        if !filter.include_deleted {
            sql.push_str(" AND deleted_at IS NULL");
        }
        if let Some(project) = filter.project {
            sql.push_str(" AND project = ?");
            args.push(Value::Text(project.to_owned()));
        }
        if let Some(status) = filter.status {
            sql.push_str(" AND status = ?");
            args.push(Value::Text(status.as_str().to_owned()));
        }
        if let Some(date) = filter.due_on_or_before {
            sql.push_str(" AND due_on <= ?");
            args.push(Value::Text(date.to_string()));
        }
        if let Some(term) = filter.search {
            // Escape SQL LIKE wildcards; all values are still bound parameters.
            let escaped = term
                .replace('\\', "\\\\")
                .replace('%', "\\%")
                .replace('_', "\\_");
            sql.push_str(" AND (title LIKE ? ESCAPE '\\' OR notes LIKE ? ESCAPE '\\')");
            args.push(Value::Text(format!("%{escaped}%")));
            args.push(Value::Text(format!("%{escaped}%")));
        }
        sql.push_str(" ORDER BY CASE status WHEN 'done' THEN 1 ELSE 0 END, due_on IS NULL, due_on, created_at, id");
        let mut stmt = self.db.prepare(&sql)?;
        let rows = stmt.query_map(params_from_iter(args.iter()), task_from_row)?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    pub fn set_status(&self, id: &str, status: TaskStatus) -> Result<Task, StorageError> {
        let mut task = self.get(id)?;
        task.change_status(status);
        self.update_existing(&task)?;
        Ok(task)
    }

    pub fn rename(&self, id: &str, title: &str) -> Result<Task, StorageError> {
        let mut task = self.get(id)?;
        task.rename(title)?;
        self.update_existing(&task)?;
        Ok(task)
    }

    /// Edit persisted fields without losing task identity or timestamps.
    /// Existing revisions are checked by the update's SQL WHERE clause.
    pub fn edit(&self, id: &str, patch: TaskPatch) -> Result<Task, StorageError> {
        let mut task = self.get(id)?;
        if task.apply_patch(patch)? {
            self.update_existing(&task)?;
        }
        Ok(task)
    }

    /// Explicit optimistic-concurrency contract for future REST/MCP adapters.
    pub fn edit_if_version(
        &self,
        id: &str,
        expected_version: i64,
        patch: TaskPatch,
    ) -> Result<Task, StorageError> {
        let mut task = self.get(id)?;
        if task.version != expected_version {
            return Err(StorageError::RevisionConflict);
        }
        if task.apply_patch(patch)? {
            self.update_existing(&task)?;
        }
        Ok(task)
    }

    /// List immediate prerequisites of an active task. A tombstoned
    /// prerequisite remains referenced and must not silently unblock work.
    pub fn get_dependencies(&self, id: &str) -> Result<Vec<String>, StorageError> {
        self.get(id)?;
        let mut statement = self.db.prepare(
            "SELECT depends_on_id FROM task_dependencies
             WHERE task_id=?1 ORDER BY depends_on_id",
        )?;
        let rows = statement.query_map(params![id], |row| row.get::<_, String>(0))?;
        Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Atomically replace a task's immediate prerequisites. The entire
    /// directed graph is kept acyclic and task revision changes at most once.
    /// Soft-deleted tasks cannot be used as new prerequisites.
    pub fn set_dependencies(
        &mut self,
        id: &str,
        dependencies: &[String],
    ) -> Result<Task, StorageError> {
        let mut requested = dependencies.to_vec();
        if requested.iter().any(|dep| dep.trim().is_empty()) {
            return Err(StorageError::InvalidDependency);
        }
        if requested.iter().any(|dep| dep == id) {
            return Err(StorageError::DependencyCycle);
        }
        requested.sort();
        if requested.windows(2).any(|pair| pair[0] == pair[1]) {
            return Err(StorageError::DuplicateDependency);
        }
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let version: i64 = tx
            .query_row(
                "SELECT version FROM tasks WHERE id=?1 AND deleted_at IS NULL",
                params![id],
                |row| row.get(0),
            )
            .optional()?
            .ok_or(StorageError::NotFound)?;
        let current: Vec<String> = {
            let mut stmt = tx.prepare(
                "SELECT depends_on_id FROM task_dependencies
                 WHERE task_id=?1 ORDER BY depends_on_id",
            )?;
            let rows = stmt.query_map(params![id], |row| row.get(0))?;
            rows.collect::<rusqlite::Result<Vec<_>>>()?
        };
        for dep in &requested {
            let exists: bool = tx.query_row(
                "SELECT EXISTS(SELECT 1 FROM tasks WHERE id=?1 AND deleted_at IS NULL)",
                params![dep],
                |row| row.get(0),
            )?;
            if !exists {
                return Err(StorageError::MissingDependency(dep.clone()));
            }
            // The outgoing edges for the edited task will be replaced below.
            // Traversing from each prerequisite must not reach the edited ID.
            let cycle: bool = tx.query_row(
                "WITH RECURSIVE reachable(id) AS (
                    SELECT depends_on_id FROM task_dependencies WHERE task_id=?1
                    UNION
                    SELECT edges.depends_on_id
                    FROM task_dependencies edges JOIN reachable r ON edges.task_id=r.id
                 )
                 SELECT EXISTS(SELECT 1 FROM reachable WHERE id=?2)",
                params![dep, id],
                |row| row.get(0),
            )?;
            if cycle {
                return Err(StorageError::DependencyCycle);
            }
        }
        if current == requested {
            tx.commit()?;
            return self.get(id);
        }
        tx.execute(
            "DELETE FROM task_dependencies WHERE task_id=?1",
            params![id],
        )?;
        for dep in &requested {
            tx.execute(
                "INSERT INTO task_dependencies(task_id,depends_on_id) VALUES (?1,?2)",
                params![id, dep],
            )?;
        }
        let updated = tx.execute(
            "UPDATE tasks SET version=version+1, updated_at=?2
             WHERE id=?1 AND version=?3 AND deleted_at IS NULL",
            params![id, Utc::now().to_rfc3339(), version],
        )?;
        if updated != 1 {
            return Err(StorageError::RevisionConflict);
        }
        tx.commit()?;
        self.get(id)
    }

    pub fn delete(&self, id: &str) -> Result<(), StorageError> {
        let mut task = self.get(id)?;
        task.soft_delete();
        self.update_existing(&task)
    }

    /// Soft-delete only if the caller has seen the latest revision. Preserve
    /// tombstones for future synchronization and prevent stale UI deletions.
    pub fn delete_if_version(
        &self,
        id: &str,
        expected_version: i64,
    ) -> Result<(), StorageError> {
        let mut task = self.get(id)?;
        if task.version != expected_version {
            return Err(StorageError::RevisionConflict);
        }
        task.soft_delete();
        self.update_existing(&task)
    }

    fn update_existing(&self, task: &Task) -> Result<(), StorageError> {
        let changed = self.db.execute(
            "UPDATE tasks SET title=?2, notes=?3, project=?4, priority=?5, status=?6, due_on=?7, updated_at=?8, completed_at=?9, version=?10, deleted_at=?11, estimate_minutes=?13 WHERE id=?1 AND version=?12 AND deleted_at IS NULL",
            params![
                task.id, task.title, task.notes, task.project, task.priority.as_str(),
                task.status.as_str(), task.due_on.map(|d| d.to_string()),
                task.updated_at.to_rfc3339(),
                task.completed_at.map(|t| t.to_rfc3339()),
                task.version, task.deleted_at.map(|t| t.to_rfc3339()),
                task.version - 1, task.estimate_minutes
            ]
        )?;
        if changed == 0 {
            return Err(StorageError::RevisionConflict);
        }
        Ok(())
    }
}

fn invalid(
    column: usize,
    error: impl std::error::Error + Send + Sync + 'static,
) -> rusqlite::Error {
    rusqlite::Error::FromSqlConversionFailure(column, Type::Text, Box::new(error))
}

fn task_from_row(row: &Row<'_>) -> rusqlite::Result<Task> {
    let priority: String = row.get(4)?;
    let status: String = row.get(5)?;
    let due: Option<String> = row.get(6)?;
    let created: String = row.get(7)?;
    let updated: String = row.get(8)?;
    let completed: Option<String> = row.get(9)?;
    let deleted: Option<String> = row.get(11)?;
    let timestamp = |s: &str, col: usize| -> rusqlite::Result<DateTime<Utc>> {
        DateTime::parse_from_rfc3339(s)
            .map(|d| d.with_timezone(&Utc))
            .map_err(|e| invalid(col, e))
    };
    Ok(Task {
        id: row.get(0)?,
        title: row.get(1)?,
        notes: row.get(2)?,
        project: row.get(3)?,
        priority: Priority::from_str(&priority).map_err(|e| invalid(4, e))?,
        status: TaskStatus::from_str(&status).map_err(|e| invalid(5, e))?,
        due_on: due
            .map(|d| NaiveDate::parse_from_str(&d, "%Y-%m-%d").map_err(|e| invalid(6, e)))
            .transpose()?,
        created_at: timestamp(&created, 7)?,
        updated_at: timestamp(&updated, 8)?,
        completed_at: completed.map(|v| timestamp(&v, 9)).transpose()?,
        version: row.get(10)?,
        deleted_at: deleted.map(|v| timestamp(&v, 11)).transpose()?,
        estimate_minutes: row.get(12)?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_filter_complete_rename_and_tombstone() {
        let store = SqliteStore::in_memory().unwrap();
        let date = NaiveDate::from_ymd_opt(2026, 11, 11).unwrap();
        let task = Task::new("Draft roadmap", "SHIORI", Priority::High, Some(date)).unwrap();
        store.insert(&task).unwrap();
        assert_eq!(store.get(&task.id).unwrap().title, "Draft roadmap");
        assert_eq!(
            store
                .list(TaskFilter {
                    search: Some("roadmap"),
                    ..Default::default()
                })
                .unwrap()
                .len(),
            1
        );
        assert_eq!(
            store
                .list(TaskFilter {
                    search: Some("%"),
                    ..Default::default()
                })
                .unwrap()
                .len(),
            0
        );
        assert_eq!(
            store
                .list(TaskFilter {
                    due_on_or_before: Some(date),
                    ..Default::default()
                })
                .unwrap()
                .len(),
            1
        );
        let renamed = store.rename(&task.id, "Approve roadmap").unwrap();
        assert_eq!(renamed.version, 2);
        let done = store.set_status(&task.id, TaskStatus::Done).unwrap();
        assert_eq!(done.version, 3);
        assert!(done.completed_at.is_some());
        store.delete(&task.id).unwrap();
        assert!(matches!(store.get(&task.id), Err(StorageError::NotFound)));
        assert_eq!(
            store
                .list(TaskFilter {
                    include_deleted: true,
                    ..Default::default()
                })
                .unwrap()
                .len(),
            1
        );
    }

    #[test]
    fn persists_after_reopening_database() {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("tasks.db");
        let task = Task::new("Persistence", "Inbox", Priority::Low, None).unwrap();
        SqliteStore::open(&path).unwrap().insert(&task).unwrap();
        assert_eq!(
            SqliteStore::open(&path)
                .unwrap()
                .get(&task.id)
                .unwrap()
                .title,
            "Persistence"
        );
    }
}
