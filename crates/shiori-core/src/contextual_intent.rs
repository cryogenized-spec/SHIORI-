//! Contextual intent memory. Derived meaning is never execution permission.
//!
//! An explicit user correction is evidence of an intended procedure, not a
//! licence for an agent to call arbitrary tools. The application must validate
//! source provenance, authorization and the procedure registry independently.
use serde::{Deserialize, Serialize};
use thiserror::Error;
use uuid::Uuid;

pub const MIN_VERIFIED_SUCCESSES: u32 = 2;

#[derive(Debug, Error, PartialEq, Eq)]
pub enum IntentError {
    #[error("invalid workspace or project identity")]
    InvalidScope,
    #[error("phrase must contain 2-160 characters")]
    InvalidPhrase,
    #[error("meaning must contain 1-2000 characters")]
    InvalidMeaning,
    #[error("procedure id must be a 1-128 character registered-operation identifier")]
    InvalidProcedure,
    #[error("correction or outcome needs a stable evidence ID")]
    InvalidEvidence,
    #[error("correction does not belong to the same expression and scope")]
    ScopeMismatch,
    #[error("verified outcome may only be recorded for the same active rule")]
    StaleOutcome,
}

fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b"._:-".contains(&b))
}

pub fn normalize_phrase(raw: &str) -> String {
    raw.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .trim_matches(|c: char| !c.is_alphanumeric())
        .to_lowercase()
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct IntentScope {
    pub workspace_id: String,
    /// None represents a workspace-wide meaning. Project-specific rules win.
    pub project_id: Option<String>,
}

impl IntentScope {
    pub fn validate(&self) -> Result<(), IntentError> {
        if !valid_id(&self.workspace_id)
            || self.project_id.as_deref().is_some_and(|id| !valid_id(id))
        {
            return Err(IntentError::InvalidScope);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct IntentCorrection {
    pub scope: IntentScope,
    pub phrase: String,
    /// Human-readable interpretation, never executable instructions.
    pub meaning: String,
    /// Identifier resolved against a trusted registry during execution.
    pub procedure_id: String,
    /// App-authenticated reference to the user's actual corrective message.
    pub evidence_id: String,
}

impl IntentCorrection {
    pub fn validate(&self) -> Result<(), IntentError> {
        self.scope.validate()?;
        let phrase = normalize_phrase(&self.phrase);
        if phrase.chars().count() < 2 || phrase.chars().count() > 160 {
            return Err(IntentError::InvalidPhrase);
        }
        if self.meaning.trim().is_empty() || self.meaning.chars().count() > 2_000 {
            return Err(IntentError::InvalidMeaning);
        }
        if !valid_id(&self.procedure_id) {
            return Err(IntentError::InvalidProcedure);
        }
        if !valid_id(&self.evidence_id) {
            return Err(IntentError::InvalidEvidence);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct IntentRule {
    pub id: String,
    pub scope: IntentScope,
    pub phrase: String,
    pub meaning: String,
    pub procedure_id: String,
    pub correction_count: u32,
    pub verified_successes: u32,
    pub revision: i64,
    pub last_evidence_id: String,
}

impl IntentRule {
    pub fn from_correction(correction: &IntentCorrection) -> Result<Self, IntentError> {
        correction.validate()?;
        Ok(Self {
            id: Uuid::now_v7().to_string(),
            scope: correction.scope.clone(),
            phrase: normalize_phrase(&correction.phrase),
            meaning: correction.meaning.trim().to_owned(),
            procedure_id: correction.procedure_id.clone(),
            correction_count: 1,
            verified_successes: 0,
            revision: 1,
            last_evidence_id: correction.evidence_id.clone(),
        })
    }

    /// Revising a meaning revokes earlier successful-use evidence.
    pub fn apply_correction(&mut self, correction: &IntentCorrection) -> Result<(), IntentError> {
        correction.validate()?;
        if self.scope != correction.scope || self.phrase != normalize_phrase(&correction.phrase) {
            return Err(IntentError::ScopeMismatch);
        }
        if self.meaning != correction.meaning.trim() || self.procedure_id != correction.procedure_id
        {
            self.verified_successes = 0;
        }
        self.meaning = correction.meaning.trim().to_owned();
        self.procedure_id.clone_from(&correction.procedure_id);
        self.last_evidence_id.clone_from(&correction.evidence_id);
        self.correction_count = self.correction_count.saturating_add(1);
        self.revision += 1;
        Ok(())
    }

    /// Only a *verified* successful use, confirmed by the host, may call this.
    pub fn record_success(
        &mut self,
        expected_revision: i64,
        evidence_id: &str,
    ) -> Result<(), IntentError> {
        if !valid_id(evidence_id) {
            return Err(IntentError::InvalidEvidence);
        }
        if self.revision != expected_revision {
            return Err(IntentError::StaleOutcome);
        }
        self.verified_successes = self.verified_successes.saturating_add(1);
        self.last_evidence_id = evidence_id.to_owned();
        self.revision += 1;
        Ok(())
    }

    pub fn well_established(&self) -> bool {
        self.verified_successes >= MIN_VERIFIED_SUCCESSES
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum ClarificationReason {
    Unrecognised,
    NeedsVerification,
    CompetingMeanings,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum IntentResolution {
    Clarify {
        reason: ClarificationReason,
        suggested: Option<IntentRule>,
    },
    /// Interpretation is sufficiently evidenced; never authorises execution.
    Interpreted { rule: IntentRule },
}

/// Exact normalized phrases only. Scope filtering precedes ranking. Future
/// synonym expansion must be provenance-aware and may not bypass this gate.
pub fn resolve_intent(
    rules: &[IntentRule],
    expression: &str,
    active_scope: &IntentScope,
) -> IntentResolution {
    if active_scope.validate().is_err() {
        return IntentResolution::Clarify {
            reason: ClarificationReason::Unrecognised,
            suggested: None,
        };
    }
    let phrase = normalize_phrase(expression);
    let mut candidates: Vec<&IntentRule> = rules
        .iter()
        .filter(|r| {
            r.scope.workspace_id == active_scope.workspace_id
                && r.phrase == phrase
                && (r.scope.project_id.is_none() || r.scope.project_id == active_scope.project_id)
        })
        .collect();
    if candidates.is_empty() {
        return IntentResolution::Clarify {
            reason: ClarificationReason::Unrecognised,
            suggested: None,
        };
    }
    if active_scope.project_id.is_some()
        && candidates
            .iter()
            .any(|r| r.scope.project_id == active_scope.project_id)
    {
        candidates.retain(|r| r.scope.project_id == active_scope.project_id);
    }
    if candidates.len() != 1 {
        return IntentResolution::Clarify {
            reason: ClarificationReason::CompetingMeanings,
            suggested: None,
        };
    }
    let rule = (*candidates[0]).clone();
    if rule.well_established() {
        IntentResolution::Interpreted { rule }
    } else {
        IntentResolution::Clarify {
            reason: ClarificationReason::NeedsVerification,
            suggested: Some(rule),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn correction(project_id: Option<&str>) -> IntentCorrection {
        IntentCorrection {
            scope: IntentScope {
                workspace_id: "personal".into(),
                project_id: project_id.map(str::to_owned),
            },
            phrase: "Make a note of this!".into(),
            meaning: "Append to the active journal, timestamped, third person".into(),
            procedure_id: "journal.append".into(),
            evidence_id: "message:001".into(),
        }
    }

    #[test]
    fn normalizes_case_whitespace_and_terminal_punctuation() {
        assert_eq!(
            normalize_phrase("  MAKE   a note of THIS!!! "),
            "make a note of this"
        );
    }
    #[test]
    fn corrected_meaning_is_suggested_until_verified() {
        let c = correction(None);
        let rule = IntentRule::from_correction(&c).unwrap();
        assert!(matches!(
            resolve_intent(&[rule], "make a note of this", &c.scope),
            IntentResolution::Clarify {
                reason: ClarificationReason::NeedsVerification,
                ..
            }
        ));
    }
    #[test]
    fn two_verified_uses_allow_low_friction_interpretation() {
        let c = correction(None);
        let mut r = IntentRule::from_correction(&c).unwrap();
        r.record_success(1, "outcome:1").unwrap();
        r.record_success(2, "outcome:2").unwrap();
        assert!(matches!(
            resolve_intent(&[r], "MAKE A NOTE OF THIS", &c.scope),
            IntentResolution::Interpreted { .. }
        ));
    }
    #[test]
    fn correction_resets_old_successes() {
        let c = correction(None);
        let mut r = IntentRule::from_correction(&c).unwrap();
        r.record_success(1, "outcome:1").unwrap();
        r.record_success(2, "outcome:2").unwrap();
        let mut newer = c.clone();
        newer.meaning = "Record only to current task".into();
        newer.procedure_id = "task.comment".into();
        newer.evidence_id = "message:002".into();
        r.apply_correction(&newer).unwrap();
        assert_eq!(r.verified_successes, 0);
        assert!(!r.well_established());
        assert_eq!(r.procedure_id, "task.comment");
    }
    #[test]
    fn project_meaning_overrides_workspace_meaning() {
        let global = IntentRule::from_correction(&correction(None)).unwrap();
        let mut local_input = correction(Some("research"));
        local_input.procedure_id = "research.journal.append".into();
        let local = IntentRule::from_correction(&local_input).unwrap();
        match resolve_intent(&[global, local], "make a note of this", &local_input.scope) {
            IntentResolution::Clarify {
                suggested: Some(rule),
                ..
            } => assert_eq!(rule.procedure_id, "research.journal.append"),
            other => panic!("unexpected result: {other:?}"),
        }
    }
    #[test]
    fn no_cross_workspace_learning() {
        let r = IntentRule::from_correction(&correction(None)).unwrap();
        let other = IntentScope {
            workspace_id: "client-b".into(),
            project_id: None,
        };
        assert!(matches!(
            resolve_intent(&[r], "make a note of this", &other),
            IntentResolution::Clarify {
                reason: ClarificationReason::Unrecognised,
                ..
            }
        ));
    }
    #[test]
    fn stale_success_cannot_reinforce_overwritten_meaning() {
        let c = correction(None);
        let mut rule = IntentRule::from_correction(&c).unwrap();
        let mut newer = c.clone();
        newer.evidence_id = "message:002".into();
        rule.apply_correction(&newer).unwrap();
        assert_eq!(
            rule.record_success(1, "outcome:stale"),
            Err(IntentError::StaleOutcome)
        );
    }
    #[test]
    fn invalid_procedure_and_evidence_are_rejected() {
        let mut c = correction(None);
        c.procedure_id = "arbitrary js".into();
        assert_eq!(c.validate(), Err(IntentError::InvalidProcedure));
        c.procedure_id = "journal.append".into();
        c.evidence_id = "".into();
        assert_eq!(c.validate(), Err(IntentError::InvalidEvidence));
    }
}
