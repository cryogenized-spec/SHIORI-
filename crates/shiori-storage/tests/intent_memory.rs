use shiori_core::contextual_intent::{
    ClarificationReason, IntentCorrection, IntentResolution, IntentScope,
};
use shiori_storage::{IntentStore, IntentStoreError};

fn scope(workspace_id: &str, project_id: Option<&str>) -> IntentScope {
    IntentScope {
        workspace_id: workspace_id.to_owned(),
        project_id: project_id.map(str::to_owned),
    }
}

fn correction(
    source: &str,
    workspace: &str,
    project: Option<&str>,
    procedure: &str,
) -> IntentCorrection {
    IntentCorrection {
        scope: scope(workspace, project),
        phrase: "make a note of this".into(),
        meaning: "Timestamped third-person entry in the current journal".into(),
        procedure_id: procedure.into(),
        evidence_id: source.into(),
    }
}

#[test]
fn corrections_are_durable_across_reopens_and_replays() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("test.intent.sqlite3");
    let c = correction("msg.001", "personal", None, "journal.append");
    let original_id;
    {
        let mut store = IntentStore::open(&path).unwrap();
        let rule = store.record_correction(&c).unwrap();
        assert_eq!(rule.revision, 1);
        original_id = rule.id.clone();
        let replay = store.record_correction(&c).unwrap();
        assert_eq!(replay.id, original_id);
        assert_eq!(replay.correction_count, 1);
    }
    {
        let store = IntentStore::open(&path).unwrap();
        let r = store.get(&original_id).unwrap().unwrap();
        assert_eq!(r.procedure_id, "journal.append");
        assert!(matches!(
            store.resolve("MAKE A NOTE OF THIS!", &c.scope).unwrap(),
            IntentResolution::Clarify {
                reason: ClarificationReason::NeedsVerification,
                ..
            }
        ));
    }
}

#[test]
fn explicit_outcomes_reduce_clarifications_but_do_not_execute() {
    let mut store = IntentStore::in_memory().unwrap();
    let c = correction("msg.001", "personal", None, "journal.append");
    let first = store.record_correction(&c).unwrap();
    let second = store.record_success(&first.id, 1, "outcome.1").unwrap();
    assert_eq!(second.verified_successes, 1);
    assert!(matches!(
        store.resolve("make a note of this", &c.scope).unwrap(),
        IntentResolution::Clarify { .. }
    ));
    let third = store.record_success(&first.id, 2, "outcome.2").unwrap();
    assert!(third.well_established());
    let replay = store.record_success(&first.id, 2, "outcome.2").unwrap();
    assert_eq!(replay.revision, 3);
    assert!(matches!(
        store.resolve("make a note of this", &c.scope).unwrap(),
        IntentResolution::Interpreted { .. }
    ));
}

#[test]
fn new_correction_revokes_old_outcome_evidence() {
    let mut store = IntentStore::in_memory().unwrap();
    let c = correction("msg.001", "personal", None, "journal.append");
    let rule = store.record_correction(&c).unwrap();
    store.record_success(&rule.id, 1, "outcome.1").unwrap();
    store.record_success(&rule.id, 2, "outcome.2").unwrap();
    let changed = correction("msg.002", "personal", None, "task.comment");
    let revised = store.record_correction(&changed).unwrap();
    assert_eq!(revised.verified_successes, 0);
    assert_eq!(revised.revision, 4);
    assert!(matches!(
        store.record_success(&rule.id, 3, "outcome.stale"),
        Err(IntentStoreError::Invalid(_))
    ));
}

#[test]
fn scope_specificity_and_workspace_isolation() {
    let mut store = IntentStore::in_memory().unwrap();
    let global = correction("msg.001", "personal", None, "journal.append");
    store.record_correction(&global).unwrap();
    let project = correction("msg.002", "personal", Some("research"), "research.record");
    store.record_correction(&project).unwrap();
    let other = scope("other", Some("research"));
    assert!(store.list(&other).unwrap().is_empty());
    match store
        .resolve("make a note of this", &project.scope)
        .unwrap()
    {
        IntentResolution::Clarify {
            suggested: Some(rule),
            ..
        } => assert_eq!(rule.procedure_id, "research.record"),
        got => panic!("unexpected: {got:?}"),
    }
    match store
        .resolve("make a note of this", &scope("personal", Some("another")))
        .unwrap()
    {
        IntentResolution::Clarify {
            suggested: Some(rule),
            ..
        } => assert_eq!(rule.procedure_id, "journal.append"),
        got => panic!("unexpected: {got:?}"),
    }
}

#[test]
fn evidence_cannot_be_reused_to_change_interpretation() {
    let mut store = IntentStore::in_memory().unwrap();
    let c = correction("msg.001", "personal", None, "journal.append");
    store.record_correction(&c).unwrap();
    let changed = correction("msg.001", "personal", None, "task.comment");
    assert!(matches!(
        store.record_correction(&changed),
        Err(IntentStoreError::EvidenceConflict)
    ));
}

#[test]
fn refuse_unknown_future_sidecar_schema() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("future.intent.sqlite3");
    let db = rusqlite::Connection::open(&path).unwrap();
    db.pragma_update(None, "user_version", 99).unwrap();
    drop(db);
    assert!(matches!(
        IntentStore::open(path),
        Err(IntentStoreError::UnsupportedSchema(99))
    ));
}


#[test]
fn revision_guard_and_revoke_preserve_scope_boundaries() {
    let mut store = IntentStore::in_memory().unwrap();
    let c = correction("msg.100", "personal", Some("Field Research"), "intent.unbound");
    let rule = store.record_correction_checked(&c, Some(0)).unwrap();
    assert_eq!(rule.revision, 1);
    assert!(matches!(
        store.record_correction_checked(
            &correction("msg.101", "personal", Some("Field Research"), "intent.unbound"),
            Some(0),
        ),
        Err(IntentStoreError::RevisionConflict)
    ));
    let updated = store.record_correction_checked(
        &correction("msg.102", "personal", Some("Field Research"), "intent.unbound"),
        Some(1),
    ).unwrap();
    assert_eq!(updated.revision, 2);
    assert_eq!(store.list_workspace("personal").unwrap().len(), 1);
    assert!(store.list_workspace("another").unwrap().is_empty());
    assert!(matches!(
        store.revoke(&updated.id, 1),
        Err(IntentStoreError::RevisionConflict)
    ));
    assert_eq!(store.list_workspace("personal").unwrap().len(), 1);
    store.revoke(&updated.id, 2).unwrap();
    assert!(store.list_workspace("personal").unwrap().is_empty());
    assert!(store.get(&updated.id).unwrap().is_none());
}

#[test]
fn revoked_evidence_can_be_replaced_without_resurrecting_old_rule() {
    let mut store = IntentStore::in_memory().unwrap();
    let c = correction("msg.200", "personal", Some("Research"), "intent.unbound");
    let first = store.record_correction_checked(&c, Some(0)).unwrap();
    store.revoke(&first.id, first.revision).unwrap();
    let replacement = store.record_correction_checked(&c, Some(0)).unwrap();
    assert_ne!(first.id, replacement.id);
    assert_eq!(replacement.verified_successes, 0);
}
