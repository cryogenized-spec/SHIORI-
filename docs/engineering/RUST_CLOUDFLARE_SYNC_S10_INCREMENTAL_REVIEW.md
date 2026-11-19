# SHIORI S10 — Incremental read-only divergence detection after S9

S10 is the first **subsequent-cycle** review step, using the S9 checkpoint as a trustworthy previous local/remote revision pairing. It detects whether the local task changed, the Cloudflare task changed, both changed, a dependency graph changed, or either copy was deleted. **It does not update either task database**, automatically merge fields, post to Cloudflare or advance the checkpoint.

Use only for a previously S2-imported task with completed S8 local apply and S9 checkpoint, still retaining the original private S4 review snapshot:

```bash
python3 cloudflare/shiori-mcp/scripts/sync_incremental_review.py \
  --canonical "$HOME/.local/share/shiori/tasks.sqlite3" \
  --shadow "$HOME/.local/share/shiori/remote.pull-preview.sqlite3" \
  --journal "$HOME/.local/share/shiori/tasks.sync.sqlite3" \
  --token-file "$HOME/.local/share/shiori/owner-token" \
  --checkpoint-file "$HOME/.local/share/shiori/device.sync-checkpoint.sqlite3" \
  --task-id '<ORIGINAL-TASK-UUID>' \
  --event-id 'sync1:<DEVICE-UUID>:<ORIGINAL-TASK-UUID>:1' \
  --confirm-read-content
```

All five input files must be private, distinct, existing regular files with no symlink/hardlink aliasing. The script verifies the S9 file's identity and stored revision/hash witness, checks that the checkpoint references the still available approved S4 snapshot, and reattests the original acknowledged S2 import. Then it makes **two owner-authenticated read requests** for the source receipt and a fresh, atomic S4 current record. This is an explicit single-task read, not background monitoring.

Classification is conservative:

- **aligned_at_current_owner_read** — both sides still have the same five common fields and dependencies as the checkpoint. An unrelated increase in the global change-feed cutoff does not falsely indicate a task edit.
- **local_only_change_for_owner_review** or **remote_only_change_for_owner_review** — one side's common fields changed since the approved base; next step requires owner confirmation and separate version-pinned push/pull. No such push/pull is performed here.
- **two_sided_content_conflict** — both sides changed. Even disjoint edits require a separate three-way field-by-field plan, fresh source checks and explicit approval.
- **dependency_conflict** or **delete_conflict** — a graph rewrite or tombstone is never automatically applied or resurrected.
- **unversioned_mutation_conflict** — changed common contents at the *same* claimed revision indicate a potentially unlogged or tampered write. Fail closed.
- **revision_without_common_content_change** — revision history advanced but common fields remain the same; may be a local-only edit or remote noncommon event. Do not equate revisions across databases.

The report contains only status, revision numbers and flags. It never prints task names, notes, IDs, token, SHA-256 payload hashes or graph members. Every report sets `safe_to_apply=false`, `automatic_sync=false`, and no-write flags. This classification does **not** establish complete Rust/cloud schema parity or guarantee remote freshness beyond the moment of authenticated read.

Synthetic tests exercise local-only, remote-only, both-side, deletion, dependency, unversioned and noncommon revision changes, same-content global cloud cutoff changes, source identity, private file protections and unchanged local/checkpoint bytes. No connected task data is used.

The next milestone is a version-pinned, **owner-reviewed incremental operation** using this classified baseline, with a durable mapping transition. Only after that can actual two-device offline convergence be tested.
