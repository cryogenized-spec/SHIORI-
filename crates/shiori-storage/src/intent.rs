//! A versioned sidecar SQLite store for optional contextual-intent memory.
//! It is deliberately independent of the canonical SHIORI task DB schema.
//! The host must authenticate actor/workspace and validate outcome provenance.
use rusqlite::{Connection, OptionalExtension, Row, TransactionBehavior, params};
use shiori_core::contextual_intent::{
    IntentCorrection, IntentError, IntentResolution, IntentRule, IntentScope, resolve_intent,
};
use std::path::Path;
use thiserror::Error;

const SCHEMA_VERSION: i64 = 1;
const RULE_FIELDS: &str = "id, workspace_id, project_id, phrase, meaning, procedure_id, correction_count, verified_successes, revision, last_evidence_id";

#[derive(Debug, Error)]
pub enum IntentStoreError {
    #[error(transparent)]
    Sql(#[from] rusqlite::Error),
    #[error(transparent)]
    Invalid(#[from] IntentError),
    #[error("rule not found")]
    NotFound,
    #[error("intent rule revision conflict")]
    RevisionConflict,
    #[error("evidence ID was reused with different content or operation")]
    EvidenceConflict,
    #[error("unsupported intent-memory schema version: {0}")]
    UnsupportedSchema(i64),
}

pub struct IntentStore {
    db: Connection,
}

fn row_to_rule(row: &Row<'_>) -> rusqlite::Result<IntentRule> {
    Ok(IntentRule {
        id: row.get(0)?,
        scope: IntentScope {
            workspace_id: row.get(1)?,
            project_id: row.get(2)?,
        },
        phrase: row.get(3)?,
        meaning: row.get(4)?,
        procedure_id: row.get(5)?,
        correction_count: row.get(6)?,
        verified_successes: row.get(7)?,
        revision: row.get(8)?,
        last_evidence_id: row.get(9)?,
    })
}

impl IntentStore {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, IntentStoreError> {
        Self::initialize(Connection::open(path)?)
    }

    pub fn in_memory() -> Result<Self, IntentStoreError> {
        Self::initialize(Connection::open_in_memory()?)
    }

    fn initialize(mut db: Connection) -> Result<Self, IntentStoreError> {
        db.execute_batch("PRAGMA foreign_keys = ON; PRAGMA busy_timeout = 4000;")?;
        let version: i64 = db.pragma_query_value(None, "user_version", |r| r.get(0))?;
        if version != 0 && version != SCHEMA_VERSION {
            return Err(IntentStoreError::UnsupportedSchema(version));
        }
        if version == 0 {
            let tx = db.transaction_with_behavior(TransactionBehavior::Immediate)?;
            tx.execute_batch(
                "CREATE TABLE intent_rules (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT,
                    phrase TEXT NOT NULL,
                    meaning TEXT NOT NULL,
                    procedure_id TEXT NOT NULL,
                    correction_count INTEGER NOT NULL CHECK(correction_count >= 1),
                    verified_successes INTEGER NOT NULL CHECK(verified_successes >= 0),
                    revision INTEGER NOT NULL CHECK(revision >= 1),
                    last_evidence_id TEXT NOT NULL
                );
                CREATE UNIQUE INDEX intent_unique_scope_phrase
                  ON intent_rules(workspace_id, COALESCE(project_id, ''), phrase);
                CREATE INDEX intent_rules_workspace ON intent_rules(workspace_id);
                CREATE TABLE intent_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    rule_id TEXT NOT NULL REFERENCES intent_rules(id),
                    event_kind TEXT NOT NULL CHECK(event_kind IN ('correction', 'success')),
                    phrase TEXT NOT NULL,
                    meaning TEXT NOT NULL,
                    procedure_id TEXT NOT NULL
                );",
            )?;
            tx.pragma_update(None, "user_version", SCHEMA_VERSION)?;
            tx.commit()?;
        }
        Ok(Self { db })
    }

    fn get_in(db: &Connection, id: &str) -> Result<Option<IntentRule>, IntentStoreError> {
        let query = format!("SELECT {RULE_FIELDS} FROM intent_rules WHERE id=?1");
        Ok(db.query_row(&query, params![id], row_to_rule).optional()?)
    }

    pub fn get(&self, id: &str) -> Result<Option<IntentRule>, IntentStoreError> {
        Self::get_in(&self.db, id)
    }

    pub fn list(&self, scope: &IntentScope) -> Result<Vec<IntentRule>, IntentStoreError> {
        scope.validate()?;
        let query = format!(
            "SELECT {RULE_FIELDS} FROM intent_rules
             WHERE workspace_id=?1 AND (project_id IS NULL OR project_id=?2)
             ORDER BY phrase, project_id"
        );
        let mut stmt = self.db.prepare(&query)?;
        let found = stmt
            .query_map(params![scope.workspace_id, scope.project_id], row_to_rule)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(found)
    }

    /// Lists all project-specific and workspace rules within one scoped workspace.
    pub fn list_workspace(&self, workspace_id: &str) -> Result<Vec<IntentRule>, IntentStoreError> {
        IntentScope { workspace_id: workspace_id.to_owned(), project_id: None }.validate()?;
        let query = format!(
            "SELECT {RULE_FIELDS} FROM intent_rules WHERE workspace_id=?1 ORDER BY phrase, project_id"
        );
        let mut stmt = self.db.prepare(&query)?;
        let rows = stmt
            .query_map(params![workspace_id], row_to_rule)?
            .collect::<rusqlite::Result<Vec<_>>>()?;
        Ok(rows)
    }

    pub fn resolve(
        &self,
        expression: &str,
        scope: &IntentScope,
    ) -> Result<IntentResolution, IntentStoreError> {
        Ok(resolve_intent(&self.list(scope)?, expression, scope))
    }

    /// Explicit revocation removes a single rule and its evidence only.
    pub fn revoke(&mut self, rule_id: &str, expected_revision: i64)
        -> Result<(), IntentStoreError>
    {
        let tx = self.db.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let rule = Self::get_in(&tx, rule_id)?.ok_or(IntentStoreError::NotFound)?;
        if rule.revision != expected_revision {
            return Err(IntentStoreError::RevisionConflict);
        }
        tx.execute("DELETE FROM intent_evidence WHERE rule_id=?1", params![rule_id])?;
        tx.execute("DELETE FROM intent_rules WHERE id=?1", params![rule_id])?;
        tx.commit()?;
        Ok(())
    }

    /// The caller has established that evidence_id refers to an actual user
    /// correction. The stored interpretation never confers execution authority.
    /// Same evidence = exact replay; changed payload = explicit conflict.
    pub fn record_correction(
        &mut self,
        correction: &IntentCorrection,
    ) -> Result<IntentRule, IntentStoreError> {
        self.record_correction_checked(correction, None)
    }

    /// Some(0) requires new; Some(revision > 0) is an optimistic update.
    /// None is permitted only for existing local CLI/test compatibility.
    pub fn record_correction_checked(
        &mut self,
        correction: &IntentCorrection,
        expected_revision: Option<i64>,
    ) -> Result<IntentRule, IntentStoreError> {
        correction.validate()?;
        let phrase = shiori_core::contextual_intent::normalize_phrase(&correction.phrase);
        let meaning = correction.meaning.trim();
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let previous: Option<(String, String, String, String, String)> = tx
            .query_row(
                "SELECT rule_id, event_kind, phrase, meaning, procedure_id
             FROM intent_evidence WHERE evidence_id=?1",
                params![correction.evidence_id],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?, r.get(3)?, r.get(4)?)),
            )
            .optional()?;
        if let Some((id, kind, old_phrase, old_meaning, old_procedure)) = previous {
            let existing = Self::get_in(&tx, &id)?.ok_or(IntentStoreError::NotFound)?;
            if kind == "correction"
                && old_phrase == phrase
                && old_meaning == meaning
                && old_procedure == correction.procedure_id
                && existing.scope == correction.scope
            {
                return Ok(existing);
            }
            return Err(IntentStoreError::EvidenceConflict);
        }
        let query = format!(
            "SELECT {RULE_FIELDS} FROM intent_rules
             WHERE workspace_id=?1 AND COALESCE(project_id, '')=?2 AND phrase=?3"
        );
        let existing = tx
            .query_row(
                &query,
                params![
                    correction.scope.workspace_id,
                    correction.scope.project_id.as_deref().unwrap_or(""),
                    phrase,
                ],
                row_to_rule,
            )
            .optional()?;
        let rule = if let Some(mut rule) = existing {
            if expected_revision.is_some_and(|expected| expected != rule.revision) {
                return Err(IntentStoreError::RevisionConflict);
            }
            rule.apply_correction(correction)?;
            tx.execute(
                "UPDATE intent_rules SET meaning=?2, procedure_id=?3,
                 correction_count=?4, verified_successes=?5, revision=?6,
                 last_evidence_id=?7 WHERE id=?1",
                params![
                    rule.id,
                    rule.meaning,
                    rule.procedure_id,
                    rule.correction_count,
                    rule.verified_successes,
                    rule.revision,
                    rule.last_evidence_id,
                ],
            )?;
            rule
        } else {
            if expected_revision.is_some_and(|expected| expected != 0) {
                return Err(IntentStoreError::RevisionConflict);
            }
            let rule = IntentRule::from_correction(correction)?;
            tx.execute(
                "INSERT INTO intent_rules (
                    id, workspace_id, project_id, phrase, meaning, procedure_id,
                    correction_count, verified_successes, revision, last_evidence_id
                 ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
                params![
                    rule.id,
                    rule.scope.workspace_id,
                    rule.scope.project_id,
                    rule.phrase,
                    rule.meaning,
                    rule.procedure_id,
                    rule.correction_count,
                    rule.verified_successes,
                    rule.revision,
                    rule.last_evidence_id,
                ],
            )?;
            rule
        };
        tx.execute(
            "INSERT INTO intent_evidence (evidence_id, rule_id, event_kind, phrase, meaning, procedure_id)
             VALUES (?1, ?2, 'correction', ?3, ?4, ?5)",
            params![
                correction.evidence_id, rule.id, phrase, meaning, correction.procedure_id,
            ],
        )?;
        tx.commit()?;
        Ok(rule)
    }

    /// Called only after independently verified, correctly authorised success.
    /// Retry of the same outcome is idempotent; stale revisions fail closed.
    pub fn record_success(
        &mut self,
        rule_id: &str,
        expected_revision: i64,
        evidence_id: &str,
    ) -> Result<IntentRule, IntentStoreError> {
        let tx = self
            .db
            .transaction_with_behavior(TransactionBehavior::Immediate)?;
        let old: Option<(String, String)> = tx
            .query_row(
                "SELECT rule_id, event_kind FROM intent_evidence WHERE evidence_id=?1",
                params![evidence_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()?;
        if let Some((previous_id, kind)) = old {
            if previous_id == rule_id && kind == "success" {
                return Self::get_in(&tx, rule_id)?.ok_or(IntentStoreError::NotFound);
            }
            return Err(IntentStoreError::EvidenceConflict);
        }
        let mut rule = Self::get_in(&tx, rule_id)?.ok_or(IntentStoreError::NotFound)?;
        rule.record_success(expected_revision, evidence_id)?;
        tx.execute(
            "UPDATE intent_rules SET verified_successes=?2, revision=?3,
             last_evidence_id=?4 WHERE id=?1",
            params![
                rule.id,
                rule.verified_successes,
                rule.revision,
                rule.last_evidence_id
            ],
        )?;
        tx.execute(
            "INSERT INTO intent_evidence (evidence_id, rule_id, event_kind, phrase, meaning, procedure_id)
             VALUES (?1, ?2, 'success', ?3, ?4, ?5)",
            params![evidence_id, rule.id, rule.phrase, rule.meaning, rule.procedure_id],
        )?;
        tx.commit()?;
        Ok(rule)
    }
}
