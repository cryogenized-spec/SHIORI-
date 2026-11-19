# SHIORI S6 — Source-bound offline reconciliation for one task

S6 is a **read-only, content-aware, operator-invoked conflict audit** of a single previously approved S2-imported task. It connects the three existing independent pieces: the canonical Rust SQLite v3 database, a separately staged S4 current-record preview, and the previously acknowledged local S2 outbox.

```bash
python3 cloudflare/shiori-mcp/scripts/sync_local_reconcile.py \
  --canonical "$HOME/.local/share/shiori/tasks.sqlite3" \
  --shadow "$HOME/.local/share/shiori/remote.pull-preview.sqlite3" \
  --outbox "$HOME/.local/share/shiori/tasks.sync.sqlite3" \
  --task-id '<ORIGINAL-TASK-UUID>' \
  --event-id 'sync1:<DEVICE-UUID>:<ORIGINAL-TASK-UUID>:1'
```

All inputs must be existing private regular files (mode `0600`). The script opens all three databases in **SQLite read-only mode** and refuses symlinks, inode/hardlink aliases, unknown schema versions, malformed source identifiers and inconsistent S4 snapshot SHA-256. It verifies that the S4 source receipt references the **same original immutable S2 event and payload hash** as the acknowledged Rust outbox. It never uploads, creates, replaces, repairs or deletes records.

The preview contains private notes and titles, which the script compares **in memory only** with the canonical Rust record. Output includes common-field mismatch counts, local/cloud revision numbers, tombstone and dependency disagreement flags, and clearly named manual blockers. It does not output any task IDs, event IDs, original payload hashes, titles, notes, credentials or dependencies. A source missing from local or cloud is never treated as safe to insert, overwrite or resurrect.

**This is not independent current-cloud attestation**: the S4 preview was valid when captured, but could now be stale. A copied receipt hash does not prove live Cloudflare identity, owner authorization or freshness; the latter must be revalidated through an authenticated online read immediately before any future approved write. The original S2 import and subsequent revisions may differ across local and remote databases, so the audit **never** equates local revision number with remote revision number.

For every report, `ready_for_apply=false`, `safe_to_apply=false`, `local_rust_sync=false` and all local/cloud write flags remain false. Even an exact common-field match does not verify all local-only data, missing source lineage after remote purge/recreation, or dependency semantics on other devices. This is the precondition review for a future explicit, backed-up, authenticated local apply command—not that command itself.

Test using `python3 -m unittest discover -s tests -p 'test_sync_local_reconcile.py' -v`. Ten synthetic cases cover two independently edited records, soft-deletes, edge divergence, missing canonical task, broken acknowledged source, tampered S4 snapshot hash, wrong receipt, insecure files, hardlinks and unknown schema. No real tasks or API are used.
