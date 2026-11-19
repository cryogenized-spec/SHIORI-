# SHIORI S4 — Explicit current-record remote snapshot (alpha)

**Development 18 November 2026.** This is an owner-authorized **read-only** building block for current-record verification, not automatic replication or permission to apply cloud data to Rust SQLite.

The `sync.record.snapshot.read` operation requests **one specific task** using `workspace_id`, `task_id` and mandatory `include_content: true`. The explicit content opt-in is intentional: unlike S1/S3 metadata scans, this operation returns the remote task's **title and notes**. It is authenticated with the same workspace-scoped owner bearer or OAuth `mcp:read` grant as the existing D1 service.

```json
{"workspace_id":"personal","task_id":"<TASK_UUID>","include_content":true}
```

The operation performs a **single primary-pinned D1 SQLite SELECT** of the current remote record (including tombstone and revision), sorted prerequisite IDs, any original S2 import receipt, and the current append-only change-feed high-water cutoff. One statement prevents combining unrelated reads into a fictitious snapshot. It returns a SHA-256 digest of the canonical JSON observation, a bounded 16 KiB source observation and flags `consistent_snapshot=true`, `automatic_apply=false`, `local_rust_sync=false`.

The SHA-256 represents the **remote observation**, not proof of canonical local equivalence, future freshness or legitimate ancestry after remote purge/recreation. A known S2 receipt attests the **historical** source of an approved import; it cannot alone prove that the current record's title, notes or relationships match Rust. For a remote-only task `source_import=null`, and its local source is unverified.

The endpoint includes soft-deleted tasks, refuses malformed/oversize dependency graphs, rejects unscoped workspaces and missing IDs, and does not mutate task or change-log state. Notes and titles are returned **only** in the user-requested single-task response; they are never introduced into the metadata-only baseline or delta feed. The legacy `tasks.get` endpoint still omits tombstones and should not be used to bootstrap a replica.

**Next:** verify local revision and current-content field parity against this read, anchor any explicit decision to the observed version and source digest, then add conflict-aware conditional writes, a separate backup/rollback path and synthetic two-device convergence acceptance. Remote fields and canonical Rust fields are not yet completely isomorphic (due dates, completion timestamps, estimates and assignees), so no blind remote overwrite is permitted.

Run tests with `npm test` in `cloudflare/shiori-mcp` and `python3 -m unittest discover -s tests -p 'test_operation_contract.py' -v`. No account data is accessed in these synthetic tests.
