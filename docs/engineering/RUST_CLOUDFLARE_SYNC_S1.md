# SHIORI S1 — Identity-safe Rust ↔ Cloudflare reconciliation

**Status (18 November 2026): implementation under PR #67; release/deployment pending CI.**
This is a *sync foundation*, not completed cross-device replication. The local Rust/SQLite task store (schema v3) and the owner's isolated Cloudflare D1 are **separate authorities** until an explicit mapping, consent, and convergence protocol have been verified.

## Implemented primitives

### 1. Content-free, tombstone-aware remote read

`sync.manifest.read` (`shiori_sync_manifest_read`) is an owner-authenticated **read-only** operation. It pages remote D1 records by stable ascending ID and returns only `id`, `version`, `status`, `updated_at`, and `deleted_at`. It deliberately omits task titles, bodies, notes and attachments, and reports `local_rust_sync: false` and `consistent_snapshot: false`.

Pages are **not** an atomic cross-request D1 snapshot: a concurrent edit may make an earlier record disappear from a later page. The preview cannot authorize a write or infer source provenance from UUID equality. This endpoint also cannot prove dependency edge versions. The route requires the owner's bearer token or the OAuth `mcp:read` grant.

### 2. Explicit local Rust outbox

The local Rust `SyncJournal` uses a dedicated SQLite database `tasks.sync.sqlite3` beside the canonical task file; it does not change `tasks.sqlite3`, its schema version, or the separate spatial sidecar. The outbox stores an immutable copy of each **explicitly staged** task revision (including source IDs, dates, notes, original version, tombstone and prerequisite IDs) with a durable origin-device UUID and deterministic event ID. Exact duplicate staging is idempotent; same-version but changed data conflicts.

The journal refuses unknown schema versions, cross-purpose canonical database paths, unsafe Unix file permissions and symlinked journal files. It starts in `pending` state, retains `conflict` records, and exposes guarded receipt/acknowledgement methods for a **future verified** remote adapter. It does not directly call Cloudflare.

Sensitive notes are present in this **local** staging file. Protect the device and backups as you would the canonical SQLite database.

### 3. Owner-controlled CLI staging (no network)

```bash
cargo build --locked -p shiori-cli
target/debug/shiori-cli show '<task-id>'
# Only after verifying the record and its revision:
target/debug/shiori-cli sync-stage '<task-id>' --if-version 3
target/debug/shiori-cli sync-queue
```

`sync-stage` requires the precise local revision. It can stage a deleted task's tombstone, but never resurrects it. `sync-queue` prints event IDs, task IDs, versions and state, **not** task text or notes. Neither command sends data or changes task status.

For a *counts-only* reconciliation requiring the separate legacy owner bearer token (not the OAuth approval code):

```bash
python3 cloudflare/shiori-mcp/scripts/sync_preview.py \
  --cli target/debug/shiori-cli --manifest \
  --token-file /private/path/to/shiori-mcp-access-token.txt
```

The script reads local content-free manifest data, fetches authenticated remote D1 manifest pages, and reports only aggregate active/tombstone/version disagreement counts. It does not send local IDs, titles or notes in request bodies; it does not write either store. If pagination or source shape is inconsistent, the comparison fails closed.

## Release gates for meaningful cross-device sync

**S2 — explicit one-way staging/import:** Introduce separately permissioned device pairing, vetted identity/provenance mapping, bounded transactional cloud batches with stable local IDs, idempotency keys, per-item remote receipts and an owner-reviewed preview/apply. Preserve untransferred fields and source backups. An HTTP 200 alone is not sufficient for acknowledging a local outbox event.

**S3 — bidirectional convergence:** Introduce consistent server change sequence/cursors, offline persisted outbound change queue, rollback/compensation log, tombstone and dependency propagation, conflict UX and tested per-field reconciliation under Rust domain rules. Refuse last-write-wins on unrelated devices, stale versions, missing dependencies or delete-vs-edit races. Treat notes/attachments as separately consented.

**S4 — spatial view state:** Keep cursor, positions and visual styles in their own versioned store. Moving a node must not change its canonical task revision or dependency graph.

The private-beta acceptance proof remains: stage a disposable task on two independent devices; edit offline on each; reconnect; detect and resolve a conflict without losing either branch; delete from one device without resurrection; export/restore; and verify same canonical IDs/versions/dependencies across Rust CLI, Android and authenticated MCP. **Do not claim that Shiori is synchronized before this proof passes.**

See [ADR 0005](../adr/0005-rust-cloudflare-sync.md), [MCP operation registry](../api/operations.v1.json) and [roadmap](../../ROADMAP.md).
