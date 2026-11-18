# ADR 0005 — Identity-safe Rust ↔ Cloudflare sync protocol

**Status:** Accepted as staged architecture; S1 identity/tombstone manifest and offline outbox developed 2026-11-18. **No import, upload, replication or bidirectional sync is enabled.**

## Decision

SHIORI remains local-first. The canonical Rust task engine and its SQLite v3 task schema do not become an untrusted replica of a new Cloudflare data model. Cloudflare D1 is a user-owned optional server; it must use the same typed application/domain rules before any write-back.

### Identity and provenance

- Every item has a globally stable native ID and explicit `origin_device_id`, `origin_namespace`, `created_at`, `revision`, `last_modified_by` and `server_sequence`.
- Existing D1 alpha task UUIDs have **no proven relation** to local Rust IDs; any equal titles are *suggestions for manual review*, not an automatic merge key.
- Preserve `local_id`, `provider`, `remote_id`, and `import_event_id` in a versioned mapping table. Never silently overwrite the canonical ID with a new cloud UUID.
- Copying attachments/notes or source provenance into the cloud requires explicit opt-in and strict scope/size limits. No content ever uploaded during a compare-only request.

### Synchronisation phases

**S0 — baseline:** `scripts/sync_preview.py` can execute Rust `bridge-dump` and authenticated remote `tasks.list`, reporting counts only. This legacy comparison is retained as a diagnostic for fixture data, but titles/UUID equality cannot authorize merging.

**S1 — manifest and durable local outbox (implemented as alpha building blocks, pending release verification):** Rust `bridge-manifest` exports content-free task IDs, revisions, statuses, tombstones and prerequisite IDs; the authenticated D1 `sync.manifest.read` operation returns bounded ID-ordered pages with remote tombstones and **no titles or notes**. The counts-only Python `--manifest` comparison detects ambiguous identity/revision and deleted-vs-active conflicts. **These D1 pages are not a consistent snapshot**, do not establish provenance, and cannot support automatic writes. A separate private `tasks.sync.sqlite3` journal now persists explicitly staged full Rust snapshots, stable per-device/event IDs, conflict and acknowledgement state. `sync-stage --if-version` and `sync-queue` never send network requests. Signed device pairing, server sequence/snapshot consistency and reviewed import are still missing.

**S2 — owner-reviewed initial import (deployed single-owner pilot, NOT automatic sync):** one owner-paired device may import exactly one new, active, revision-1, dependency-free task after a content-free SHA-256 preview and separate approval. Remote D1 stores the full original native JSON and an authenticated content-free receipt, while preserving the canonical local UUID and refusing collisions/tombstones. A separate explicit local client verifies the receipt before acknowledging the outbox. No automatic upload, multi-revision merging, dependency import, bulk transfer, or bidirectional sync. See [S2 guide](../engineering/RUST_CLOUDFLARE_SYNC_S2.md).

**S3 — incremental events (read-only metadata feed deployed; private metadata-only local inbox merged):** append-only D1 task/edge change events, high-water cursor and explicit baseline-needed flag are implemented. Still missing: safe historical snapshot-and-cursor pairing, verified initial source provenance, per-field conflict resolution, invalid/dangling edge checks, reviewed tombstone propagation and reversible UX. **Two-way replication has not been enabled.** Prohibit same-ID updates with stale revisions; no silent last-write-wins. Treat personal note bodies and attachments as separately permissioned data.

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
