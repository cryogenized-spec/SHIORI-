# SHIORI S5 — Owner-reviewed common-field compare-and-swap

**Engineering alpha, 18 November 2026.** S5 introduces a real opt-in **remote task edit** for one historically approved S2-imported task. It does not directly update a canonical Rust task database or automatically synchronize Android.

The core safety model is three-way comparison: an offline device retains its last observed base; the user changes selected local fields; a fresh S4 `sync.record.snapshot.read` returns the server's actual current record. `sync_conflict_plan.py` compares `base`, intended changed common fields and `remote`. Concurrent edits to the same field, tombstone-vs-edit, changes in prerequisite edges, missing import receipt, regressed revisions or mismatched source lineage are **manual review blockers**. Disjoint edits can be proposed against the **latest** remote revision after explicit owner approval, preserving other changes. The plan contains a private task patch but must never print notes or automatic execution commands.

The S5 server operation `sync.record.apply` requires:

- An authenticated owner credential with write scope, the specific task ID and the ID of an **actively paired, non-revoked owner device**. A device UUID is an owner-scoped identity label, **not cryptographic possession proof**.
- Exact matching original `source_event_id` and `source_payload_sha256` from the first S2 import receipt. Remote-only tasks or tasks without this history cannot use this sync-specific operation.
- `expected_revision` and `expected_record_sha256` from the fresh S4 current-record snapshot, plus **`owner_approved=true`**, bounded changed fields and a stable idempotency key.
- A non-deleted task. Soft deletions are never silently reversed. Dependency edits are out of scope for this atomic scalar operation.

Only title, notes, project, status and priority are eligible for the first CAS; due dates, estimates, assignees, completion timestamps, attachments, task comments and dependency rewiring are deliberately excluded until local/remote schema parity and guarded graph operations are implemented. The D1 worker verifies the submitted receipt and exact remote fingerprint, then commits the **single conditional UPDATE** with `WHERE version=expected_revision AND deleted_at IS NULL`, incrementing revision once and storing the matching idempotency result **in the same atomic transaction**. A conflicting writer or changed record receives a conflict error, not last-write-wins behavior. Repeating the identical request returns the prior result without a second update. No private note/title is echoed in the apply response.

This means that **remote mutation code exists** and can be tested using synthetic fixtures, but local canonical apply, continuous background sync, multiple-source field parity, rollback for fully distributed changes and physical two-device acceptance are still separate release gates. Do not claim complete Rust↔D1 convergence on this S5 milestone alone.

## Synthetic acceptance

```bash
python3 -m unittest discover -s tests -p 'test_sync_conflict_plan.py' -v
cd cloudflare/shiori-mcp && npm test
```

The fixtures exercise two devices starting at revision 1. Device A proposes a status edit to revision 2; device B's independent notes change is merged against revision 2 after explicit approval to revision 3. Both then read an identical latest snapshot. Other tests refuse overlapping edits, deletion resurrection, changed dependencies, wrong source identity, invalid request/owner approval, revocation and stale CAS. The test's two-device replicas are **synthetic**: this is not a substitute for two physical Android devices, offline/disconnected real-world tests or canonical Rust local-write parity.

Do not invoke `sync.record.apply` against actual tasks until the owner has inspected the selected record and explicitly reviewed the intended changes. Initial registration and deployment should be followed by one disposable fixture-only integration test.
