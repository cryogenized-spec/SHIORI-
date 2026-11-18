//! Local-only, crash-durable synchronization outbox.
//! This is NOT a network client. Staging a task writes only a separate local
//! SQLite journal. Actual remote import requires a distinct reviewed command.
use jiff::Timestamp;
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use serde::{Deserialize, Serialize};
use shiori_core::{Task, utc_rfc3339};
use std::{collections::BTreeSet, path::Path};
use thiserror::Error;
use uuid::Uuid;

const SCHEMA_VERSION: i64 = 1;

#[derive(Debug, Error)]
pub enum SyncJournalError {
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Json(#[from] serde_json::Error),
    #[error("unsupported outbox schema version {0}; do not overwrite newer data")]
    UnsupportedSchema(i64),
    #[error("invalid task identity, revision or prerequisite set")]
    InvalidSnapshot,
    #[error("sync outbox must be a private, regular local file (not a symlink)")]
    UnsafeJournalFile,
    #[error("version-zero file contains other application tables; refusing to modify it")]
    WrongDatabase,
    #[error("same task identity/revision was already staged with different contents")]
    SnapshotConflict,
    #[error("event is missing, already acknowledged or conflicting")]
    EventConflict,
    #[error("remote receipt does not match the staged task identity/version")]
    ReceiptMismatch,
}

/// A lossless copy of a native Task. User notes and other fields are stored
/// locally in this journal, not automatically uploaded or printed.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncEnvelope {
    pub schema_version: u32,
    pub event_id: String,
    pub origin_device_id: String,
    pub workspace_id: String,
    pub task: Task,
    pub depends_on: Vec<String>,
}

/// Content-free projection intended for regular CLI inspection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SyncQueueItem {
    pub event_id: String,
    pub task_id: String,
    pub local_version: i64,
    pub state: String,
    pub remote_version: Option<i64>,
    pub created_at: String,
}

pub struct SyncJournal {
    db: Connection,
    device_id: String,
}

impl SyncJournal {
    /// Opens a *separate* local sidecar; never upgrades or writes canonical
    /// `tasks.sqlite3`. Unknown future schema versions are rejected.
    pub fn open(path: impl AsRef<Path>) -> Result<Self, SyncJournalError> {
        let path = path.as_ref();
        #[cfg(unix)]
        {
            use std::fs::{OpenOptions, symlink_metadata};
            use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
            match symlink_metadata(path) {
                Ok(info) => {
                    if !info.is_file()
                        || info.file_type().is_symlink()
                        || info.permissions().mode() & 0o077 != 0
                    {
                        return Err(SyncJournalError::UnsafeJournalFile);
                    }
                }
                Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
                    let _file = OpenOptions::new()
                        .write(true)
                        .create_new(true)
                        .mode(0o600)
                        .open(path)?;
                }
                Err(e) => return Err(e.into()),
            }
        }
        let mut db = Connection::open(path)?;
        db.execute_batch("PRAGMA busy_timeout=4000; PRAGMA foreign_keys=ON;")?;
        let version: i64 = db.pragma_query_value(None, "user_version", |r| r.get(0))?;
        if version != 0 && version != SCHEMA_VERSION {
            return Err(SyncJournalError::UnsupportedSchema(version));
        }
        if version == 0 {
            let other_tables: i64 = db.query_row(
                "SELECT COUNT(*) FROM sqlite_master
                 WHERE type='table' AND name NOT LIKE 'sqlite_%'",
                [],
                |r| r.get(0),
            )?;
            if other_tables != 0 {
                return Err(SyncJournalError::WrongDatabase);
            }
            let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
            tx.execute_batch(
                "CREATE TABLE sync_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE sync_outbox (
                    event_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    local_version INTEGER NOT NULL CHECK(local_version > 0),
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending'
                        CHECK(state IN ('pending','acknowledged','conflict')),
                    remote_version INTEGER CHECK(remote_version IS NULL OR remote_version > 0),
                    remote_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(task_id,local_version)
                );
                CREATE INDEX idx_sync_outbox_state ON sync_outbox(state,created_at,event_id);",
            )?;
            tx.execute(
                "INSERT INTO sync_meta(key,value) VALUES('device_id',?)",
                [Uuid::now_v7().to_string()],
            )?;
            tx.pragma_update(None, "user_version", SCHEMA_VERSION)?;
            tx.commit()?;
        }
        let device_id: String = db.query_row(
            "SELECT value FROM sync_meta WHERE key='device_id'",
            [],
            |r| r.get(0),
        )?;
        if Uuid::parse_str(&device_id).is_err() {
            return Err(SyncJournalError::InvalidSnapshot);
        }
        Ok(Self { db, device_id })
    }

    pub fn device_id(&self) -> &str {
        &self.device_id
    }

    /// Explicitly stage a native snapshot. Repeated staging of *identical*
    /// task version and dependencies returns the original event without
    /// creating another queue record. Divergent same-version snapshots fail.
    pub fn stage(
        &mut self,
        task: &Task,
        dependencies: &[String],
    ) -> Result<(SyncQueueItem, bool), SyncJournalError> {
        if task.id.is_empty() || task.id.len() > 160 || task.version < 1 {
            return Err(SyncJournalError::InvalidSnapshot);
        }
        let mut sorted = BTreeSet::new();
        for id in dependencies {
            if id.is_empty() || id.len() > 160 || id == &task.id || !sorted.insert(id.clone()) {
                return Err(SyncJournalError::InvalidSnapshot);
            }
        }
        if task.deleted_at.is_some() && !dependencies.is_empty() {
            return Err(SyncJournalError::InvalidSnapshot);
        }
        let event_id = format!("sync1:{}:{}:{}", self.device_id, task.id, task.version);
        let envelope = SyncEnvelope {
            schema_version: 1,
            event_id: event_id.clone(),
            origin_device_id: self.device_id.clone(),
            workspace_id: "personal".to_owned(),
            task: task.clone(),
            depends_on: sorted.into_iter().collect(),
        };
        let payload = serde_json::to_string(&envelope)?;
        let now = utc_rfc3339(Timestamp::now());
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let existing: Option<String> = tx
            .query_row(
                "SELECT payload_json FROM sync_outbox WHERE task_id=? AND local_version=?",
                params![task.id, task.version],
                |r| r.get(0),
            )
            .optional()?;
        let changed = match existing {
            Some(old) if old == payload => false,
            Some(_) => return Err(SyncJournalError::SnapshotConflict),
            None => {
                tx.execute(
                    "INSERT INTO sync_outbox(event_id,task_id,local_version,payload_json,created_at,updated_at)
                     VALUES(?,?,?,?,?,?)",
                    params![event_id,task.id,task.version,payload,now,now],
                )?;
                true
            }
        };
        let item = Self::read_item(&tx, &event_id)?.ok_or(SyncJournalError::EventConflict)?;
        tx.commit()?;
        Ok((item, changed))
    }

    fn read_item(
        db: &Connection,
        event_id: &str,
    ) -> Result<Option<SyncQueueItem>, rusqlite::Error> {
        db.query_row(
            "SELECT event_id,task_id,local_version,state,remote_version,created_at
             FROM sync_outbox WHERE event_id=?",
            [event_id],
            |r| {
                Ok(SyncQueueItem {
                    event_id: r.get(0)?,
                    task_id: r.get(1)?,
                    local_version: r.get(2)?,
                    state: r.get(3)?,
                    remote_version: r.get(4)?,
                    created_at: r.get(5)?,
                })
            },
        )
        .optional()
    }

    pub fn list(&self, limit: usize) -> Result<Vec<SyncQueueItem>, SyncJournalError> {
        let mut stmt = self.db.prepare(
            "SELECT event_id,task_id,local_version,state,remote_version,created_at
             FROM sync_outbox ORDER BY created_at,event_id LIMIT ?",
        )?;
        let rows = stmt.query_map([limit.min(500) as i64], |r| {
            Ok(SyncQueueItem {
                event_id: r.get(0)?,
                task_id: r.get(1)?,
                local_version: r.get(2)?,
                state: r.get(3)?,
                remote_version: r.get(4)?,
                created_at: r.get(5)?,
            })
        })?;
        Ok(rows.collect::<Result<Vec<_>, _>>()?)
    }

    /// Content-bearing read for a future *opt-in* authenticated upload client.
    /// Never call it during read-only reconciliation or print it by default.
    pub fn staged_envelope(&self, event_id: &str) -> Result<SyncEnvelope, SyncJournalError> {
        let value: String = self
            .db
            .query_row(
                "SELECT payload_json FROM sync_outbox WHERE event_id=? AND state='pending'",
                [event_id],
                |r| r.get(0),
            )
            .optional()?
            .ok_or(SyncJournalError::EventConflict)?;
        Ok(serde_json::from_str(&value)?)
    }

    /// Called *only after* a client verifies an authenticated remote receipt.
    /// The canonical task and pending newer events are never changed.
    pub fn acknowledge(
        &mut self,
        event_id: &str,
        remote_id: &str,
        remote_version: i64,
        received_task_id: &str,
        received_local_version: i64,
    ) -> Result<bool, SyncJournalError> {
        if remote_id.is_empty() || remote_version < 1 {
            return Err(SyncJournalError::ReceiptMismatch);
        }
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let old = Self::read_item(&tx, event_id)?.ok_or(SyncJournalError::EventConflict)?;
        if old.task_id != received_task_id || old.local_version != received_local_version {
            return Err(SyncJournalError::ReceiptMismatch);
        }
        let existing: Option<(String,i64)> = tx.query_row(
            "SELECT remote_id,remote_version FROM sync_outbox WHERE event_id=? AND state='acknowledged'",
            [event_id], |r| Ok((r.get(0)?,r.get(1)?)),
        ).optional()?;
        if let Some((id, version)) = existing {
            if id == remote_id && version == remote_version {
                return Ok(false);
            }
            return Err(SyncJournalError::ReceiptMismatch);
        }
        let changed = tx.execute(
            "UPDATE sync_outbox SET state='acknowledged',remote_id=?,remote_version=?,updated_at=?
             WHERE event_id=? AND state='pending'",
            params![
                remote_id,
                remote_version,
                utc_rfc3339(Timestamp::now()),
                event_id
            ],
        )?;
        if changed != 1 {
            return Err(SyncJournalError::EventConflict);
        }
        tx.commit()?;
        Ok(true)
    }

    /// Retain conflicting content and provenance for explicit human review.
    pub fn mark_conflict(&mut self, event_id: &str) -> Result<(), SyncJournalError> {
        let changed = self.db.execute(
            "UPDATE sync_outbox SET state='conflict',updated_at=?
             WHERE event_id=? AND state='pending'",
            params![utc_rfc3339(Timestamp::now()), event_id],
        )?;
        if changed != 1 {
            return Err(SyncJournalError::EventConflict);
        }
        Ok(())
    }
}
