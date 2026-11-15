# ADR 0005 — Identity-safe Rust ↔ Cloudflare sync protocol

**Status:** Proposed, 2026-11-15. Read-only comparison implemented. **No import, upload, replication or bidirectional sync is enabled.**

## Decision

SHIORI remains local-first. The canonical Rust task engine and its SQLite v3 task schema do not become an untrusted replica of a new Cloudflare data model. Cloudflare D1 is a user-owned optional server; it must use the same typed application/domain rules before any write-back.

### Identity and provenance

- Every item has a globally stable native ID and explicit `origin_device_id`, `origin_namespace`, `created_at`, `revision`, `last_modified_by` and `server_sequence`.
- Existing D1 alpha task UUIDs have **no proven relation** to local Rust IDs; any equal titles are *suggestions for manual review*, not an automatic merge key.
- Preserve `local_id`, `provider`, `remote_id`, and `import_event_id` in a versioned mapping table. Never silently overwrite the canonical ID with a new cloud UUID.
- Copying attachments/notes or source provenance into the cloud requires explicit opt-in and strict scope/size limits. No content ever uploaded during a compare-only request.

### Synchronisation phases

**S0 — present:** `scripts/sync_preview.py` executes a Rust `bridge-dump` and authenticated read-only remote `tasks.list`. It compares stable IDs and reports count-only conflicts; it does not execute any write operation and does not expose notes in its output.

**S1 — preview-only snapshot protocol:** define signed/permissioned device identity, read-only change manifests, paginated full snapshot hashes, tombstones and snapshot version indicators. Provide `sync.preview` with explicit missing/modified/conflict counts and source evidence. No write before device pairing.

**S2 — initial explicit upload (one direction):** user approves a reviewed mapping; use idempotent task batches, transactional outbox, chunked transfers, per-item results and rollback journal. Never batch-ack uncommitted writes. Preserve original task IDs and dependency references. Imported cloud records are isolated until linked to a verified owner.

**S3 — bidirectional replication:** incremental delta cursor, locally queued offline edits, per-field conflict resolution, invalid/dangling edge checks, tombstone propagation and conflict UX. Prohibit same-ID updates with stale revisions; no silent last-write-wins. Treat personal note bodies and attachments as separately permissioned data.

**S4 — view state:** sync camera, lock, node coordinates and connector preferences independently of canonical task revisions. Local SQLite sidecar v1 is view-specific; cross-device layouts can intentionally differ. A position update never changes a task status or dependency.

### Required negative tests

- Duplicate replay and partial transaction failure must not create duplicate tasks.
- Equal names must not merge distinct people, repairs or customers.
- Delete/tombstone must not resurrect when a disconnected device comes online.
- Denied client or revoked tokens cannot fetch sync pages.
- Mutated prerequisite links must be cycle-checked in Rust and approved separately.
- Changing layout cannot inadvertently update task/domain state.
- Network loss halfway through a batch must be recoverable without guessing commits.
- A read-only comparison must not leak any local user data to the remote API.
- Existing Android backup/recovery and canonical SQLite schema v3 remain compatible.

### Ownership and security

The account holder owns the Cloudflare deployment and D1 records. Authorization scopes separate cloud reads, task writes, sync upload and external provider actions. For personal deployment, cloud resources are not shared across accounts. The owner can revoke access; a revoke must stop new sync, but must not silently destroy offline task data.

**Implementation gate:** Only mark the server "synchronized" when a fixture-backed two-device offline/online test passes, including conflict, deletion, idempotency, migration and rollback. An operational OAuth MCP is not evidence of completed synchronization.
