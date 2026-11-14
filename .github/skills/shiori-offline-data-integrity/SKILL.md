---
name: shiori-offline-data-integrity
description: Design and test SHIORI's offline-first tasks, SQLite state, synchronization, conflict resolution, tombstones, migrations, backups, restores, and recurrence semantics. Use when changes affect persistence, multiple devices, data recovery, out-of-order updates, or any possibility of user-data loss.
---

# SHIORI offline data integrity

SHIORI must remain useful without an account, network connection, Cloudflare or AI. Read `ROADMAP.md`, the storage crate, and sync-related ADRs before making decisions.

## Rules

- Prefer a well-defined, versioned operation/change contract over ad hoc full-record overwrites. Record origin/device identity, operation identity, ordering metadata, schema version, and idempotency where needed.
- Explicitly separate local identity, per-workspace authorization, task identity and task revision. Do not equate synchronized records merely because their visible titles match.
- Use tombstones and retention policy; offline deletes must not resurrect after reconnect.
- Never choose "last write wins" for concurrent edits without an explicit conflict policy and a test for data preservation.
- Ensure retries are idempotent. Interrupted sync must resume without duplicated tasks or skipped operations.
- Preserve task dates and timezone intent across locale and DST changes, especially for recurrence exceptions.
- Never read SQLite while copying a live DB file. Use SQLite's supported online-backup facilities or verified `VACUUM INTO` with restore tests.
- Migrations need forward-compatibility fixtures, schema-version checks and robust rollback/recovery plans; fail without corrupting records.

## Tests to require

Generate two-device sequences: A edits offline, B edits, syncs out of order, retries, deletes, restores, changes timestamps, and reconnects. Verify convergence and conflict visibility. Include deterministic clocks and fixture-based migrations. Check failure injection, power loss, malformed imports and backup/restore fidelity.

At every stage distinguish tests that run against existing SQLite features from sync/backup/migration capabilities not yet built. A cold closed-file copy test is **not** proof of safe online backups.
