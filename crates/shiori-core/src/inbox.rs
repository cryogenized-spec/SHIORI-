//! SHIORI-owned capture inbox domain model (SH-005).
//!
//! This module is intentionally independent of SQLite, transport, MCP and
//! ClickUp. It does not persist items or create tasks. Application services
//! will coordinate durable, atomic conversion and authorization.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use thiserror::Error;
use uuid::Uuid;

/// Keep the capture text bounded until attachment storage has its own quota.
pub const MAX_INBOX_TEXT_CHARS: usize = 65_536;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum InboxSource {
    Local,
    Ocr,
    Import,
    /// A source reference, not authority to write to the remote service.
    External {
        provider: String,
        account_id: String,
        workspace_id: String,
        resource_kind: String,
        resource_id: String,
    },
}

impl InboxSource {
    fn validate(&self) -> Result<(), InboxError> {
        if let Self::External {
            provider,
            account_id,
            workspace_id,
            resource_kind,
            resource_id,
        } = self
        {
            for field in [
                provider,
                account_id,
                workspace_id,
                resource_kind,
                resource_id,
            ] {
                if field.trim().is_empty() || field.chars().count() > 256 {
                    return Err(InboxError::InvalidSource);
                }
            }
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InboxState {
    Unprocessed,
    Triaged,
    Linked,
    Archived,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InboxDisposition {
    Task,
    Memo,
    FollowUp,
    Reference,
}

/// A backlink to an independently created SHIORI item, not a provider ID.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct InboxLink {
    pub kind: InboxDisposition,
    pub local_id: String,
}

#[derive(Debug, Error, PartialEq, Eq)]
pub enum InboxError {
    #[error("inbox capture cannot be empty")]
    EmptyCapture,
    #[error("inbox capture exceeds the 65536-character limit")]
    CaptureTooLong,
    #[error("external source requires nonempty bounded identity fields")]
    InvalidSource,
    #[error("inbox item is archived")]
    Archived,
    #[error("inbox item is already linked; do not create duplicates")]
    AlreadyLinked,
    #[error("inbox item must be triaged to the matching target type")]
    NotTriagedForTarget,
    #[error("linked local record ID is invalid")]
    InvalidLocalId,
    #[error("mutation timestamp cannot precede the previous update")]
    TimestampRegressed,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InboxItem {
    pub id: String,
    pub text: String,
    pub source: InboxSource,
    pub state: InboxState,
    pub disposition: Option<InboxDisposition>,
    pub linked: Option<InboxLink>,
    pub captured_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
    pub version: i64,
}

impl InboxItem {
    /// Construct a local capture with an explicit clock for deterministic
    /// testing and future event replay. Capturing never creates a task.
    pub fn capture_text(
        text: &str,
        source: InboxSource,
        at: DateTime<Utc>,
    ) -> Result<Self, InboxError> {
        let text = text.trim();
        if text.is_empty() {
            return Err(InboxError::EmptyCapture);
        }
        if text.chars().count() > MAX_INBOX_TEXT_CHARS {
            return Err(InboxError::CaptureTooLong);
        }
        source.validate()?;
        Ok(Self {
            id: Uuid::now_v7().to_string(),
            text: text.to_owned(),
            source,
            state: InboxState::Unprocessed,
            disposition: None,
            linked: None,
            captured_at: at,
            updated_at: at,
            version: 1,
        })
    }

    /// A proposal/classification, not a task creation or provider write.
    pub fn triage(
        &mut self,
        disposition: InboxDisposition,
        at: DateTime<Utc>,
    ) -> Result<bool, InboxError> {
        match self.state {
            InboxState::Archived => return Err(InboxError::Archived),
            InboxState::Linked => return Err(InboxError::AlreadyLinked),
            InboxState::Unprocessed | InboxState::Triaged => {}
        }
        if self.disposition == Some(disposition) && self.state == InboxState::Triaged {
            return Ok(false);
        }
        self.validate_timestamp(at)?;
        self.disposition = Some(disposition);
        self.state = InboxState::Triaged;
        self.bump(at);
        Ok(true)
    }

    /// Records a link only after the application service has atomically
    /// created or resolved the target. Repeated requests are idempotent.
    pub fn link_existing(
        &mut self,
        kind: InboxDisposition,
        local_id: &str,
        at: DateTime<Utc>,
    ) -> Result<bool, InboxError> {
        if local_id.trim().is_empty() || local_id != local_id.trim() || local_id.len() > 256 {
            return Err(InboxError::InvalidLocalId);
        }
        if let Some(existing) = &self.linked {
            if existing.kind == kind && existing.local_id == local_id {
                return Ok(false);
            }
            return Err(InboxError::AlreadyLinked);
        }
        if self.state == InboxState::Archived {
            return Err(InboxError::Archived);
        }
        if self.state != InboxState::Triaged || self.disposition != Some(kind) {
            return Err(InboxError::NotTriagedForTarget);
        }
        self.validate_timestamp(at)?;
        self.linked = Some(InboxLink {
            kind,
            local_id: local_id.to_owned(),
        });
        self.state = InboxState::Linked;
        self.bump(at);
        Ok(true)
    }

    /// Archiving is not deletion and preserves capture provenance and links.
    pub fn archive(&mut self, at: DateTime<Utc>) -> Result<bool, InboxError> {
        if self.state == InboxState::Archived {
            return Ok(false);
        }
        self.validate_timestamp(at)?;
        self.state = InboxState::Archived;
        self.bump(at);
        Ok(true)
    }

    /// Restores the most informative prior state without losing triage/link.
    pub fn restore(&mut self, at: DateTime<Utc>) -> Result<bool, InboxError> {
        if self.state != InboxState::Archived {
            return Ok(false);
        }
        self.validate_timestamp(at)?;
        self.state = if self.linked.is_some() {
            InboxState::Linked
        } else if self.disposition.is_some() {
            InboxState::Triaged
        } else {
            InboxState::Unprocessed
        };
        self.bump(at);
        Ok(true)
    }

    fn validate_timestamp(&self, at: DateTime<Utc>) -> Result<(), InboxError> {
        if at < self.updated_at {
            return Err(InboxError::TimestampRegressed);
        }
        Ok(())
    }

    fn bump(&mut self, at: DateTime<Utc>) {
        self.updated_at = at;
        self.version += 1;
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::{Duration, TimeZone};

    fn now() -> DateTime<Utc> {
        Utc.with_ymd_and_hms(2026, 11, 14, 9, 0, 0).unwrap()
    }

    #[test]
    fn capturing_is_not_task_creation_or_automatic_triage() {
        let item = InboxItem::capture_text("  Call supplier  ", InboxSource::Local, now()).unwrap();
        assert_eq!(item.text, "Call supplier");
        assert_eq!(item.state, InboxState::Unprocessed);
        assert!(item.disposition.is_none());
        assert!(item.linked.is_none());
        assert_eq!(item.version, 1);
        assert_eq!(item.captured_at, now());
    }

    #[test]
    fn invalid_capture_and_source_rejected() {
        assert_eq!(
            InboxItem::capture_text(" \n ", InboxSource::Local, now()).unwrap_err(),
            InboxError::EmptyCapture
        );
        assert_eq!(
            InboxItem::capture_text(
                &"a".repeat(MAX_INBOX_TEXT_CHARS + 1),
                InboxSource::Import,
                now()
            )
            .unwrap_err(),
            InboxError::CaptureTooLong
        );
        assert_eq!(
            InboxItem::capture_text(
                "Work",
                InboxSource::External {
                    provider: "clickup".into(),
                    account_id: String::new(),
                    workspace_id: "w".into(),
                    resource_kind: "task".into(),
                    resource_id: "t".into()
                },
                now()
            )
            .unwrap_err(),
            InboxError::InvalidSource
        );
    }

    #[test]
    fn link_requires_explicit_matching_triage_and_is_idempotent() {
        let mut item =
            InboxItem::capture_text("Supplier reply", InboxSource::Local, now()).unwrap();
        let t1 = now() + Duration::seconds(1);
        assert_eq!(
            item.link_existing(InboxDisposition::Task, "task-1", t1),
            Err(InboxError::NotTriagedForTarget)
        );
        assert!(item.triage(InboxDisposition::Task, t1).unwrap());
        assert!(!item.triage(InboxDisposition::Task, t1).unwrap());
        let t2 = t1 + Duration::seconds(1);
        assert_eq!(
            item.link_existing(InboxDisposition::Memo, "memo-1", t2),
            Err(InboxError::NotTriagedForTarget)
        );
        assert!(
            item.link_existing(InboxDisposition::Task, "task-1", t2)
                .unwrap()
        );
        assert!(
            !item
                .link_existing(InboxDisposition::Task, "task-1", t2)
                .unwrap()
        );
        assert_eq!(
            item.link_existing(InboxDisposition::Task, "task-2", t2),
            Err(InboxError::AlreadyLinked)
        );
        assert_eq!(item.version, 3);
        assert_eq!(item.state, InboxState::Linked);
    }

    #[test]
    fn archive_restore_preserves_source_triage_and_link() {
        let mut item = InboxItem::capture_text("Note", InboxSource::Ocr, now()).unwrap();
        let at = now() + Duration::seconds(1);
        item.triage(InboxDisposition::Memo, at).unwrap();
        item.link_existing(InboxDisposition::Memo, "memo-1", at)
            .unwrap();
        item.archive(at).unwrap();
        assert!(!item.archive(at).unwrap());
        assert_eq!(
            item.triage(InboxDisposition::Task, at),
            Err(InboxError::Archived)
        );
        assert!(item.restore(at).unwrap());
        assert_eq!(item.state, InboxState::Linked);
        assert_eq!(item.source, InboxSource::Ocr);
        assert_eq!(item.linked.as_ref().unwrap().local_id, "memo-1");
    }

    #[test]
    fn stale_timestamps_do_not_partially_mutate() {
        let mut item = InboxItem::capture_text("Note", InboxSource::Local, now()).unwrap();
        let old = now() - Duration::seconds(1);
        assert_eq!(
            item.triage(InboxDisposition::Task, old),
            Err(InboxError::TimestampRegressed)
        );
        assert_eq!(item.disposition, None);
        assert_eq!(item.state, InboxState::Unprocessed);
        assert_eq!(item.version, 1);
    }
}
