# SHIORI S3 — Remote append-only change feed (read-only foundation)

**Alpha development — 18 November 2026.** Not yet two-way synchronization. PR for S3 adds a content-free change cursor and fixture tests; it does **not** mutate the user's Rust SQLite database, automatically transfer task contents or authorize cloud data as a local source of truth.

## Why a change log?

The S1 `sync.manifest.read` operation can compare remote identities, revisions and tombstones, but pagination is not an atomic snapshot. Without an immutable sequence of changes a disconnected device can miss an edit or resurrect a deleted task. S3 creates an append-only `remote_change_log` in D1, using SQLite triggers on task insertion, update, deletion/purge and prerequisite addition/removal. Existing task records require a **baseline manifest** because events before trigger installation are not backfilled.

### Remote API: `sync.changes.read`

Owner-authenticated, content-free, read-only; OAuth `mcp:read` sufficient. The method uses a D1 **first-primary** session on every request. Responses contain only sequential integer `seq`, event `kind`, task ID, optional prerequisite ID, task revision where applicable and event time. No task body, note, project, due date, attachment or token is returned.

Parameters: `workspace_id` (required), `cursor` (last processed sequence; defaults to 0), `limit` (1–100), optional `cutoff` (a fixed high-water sequence returned by the first page).

The first page reads the latest sequence `H` and serves changes with `cursor < seq <= H`. For subsequent pages, pass the unchanged `cutoff=H` and the returned `next_cursor`. When `next_cursor=null`, **persist `checkpoint_cursor`** as the last durable checkpoint for a future poll. A client must not advance this checkpoint unless all returned events were safely journaled; it must never infer task content or canonical provenance from a sequence number. New events after `H` appear only on the next poll.

`baseline_required=true` is intentionally permanent until S3 includes a verified snapshot-and-cursor protocol. An empty change list is **not proof that the remote task set is empty**.

## Known limitations and next gates

- A change event describes *that* something changed, not the full task data. Fetching current state later may yield a newer revision, so compare versions and preserve both sides before applying any write.
- The feed includes each *committed* D1 task/edge transition captured **after trigger installation**. The log is not a source of historical remote state.
- Remote hard-purge events are captured for audit, but Shiori's normal deletion remains a versioned **soft tombstone**. Never auto-delete a local record on a remote purge.
- Event sequences are global across workspaces, but response rows are strictly workspace-scoped. Gaps are allowed; do not demand contiguous numbers.
- Visual positions are separate and do not alter task revisions; these are not currently part of canonical task-change feed.
- Pending for S3: verified first-snapshot high-water pairing, signed device identity, local durable pull journal, reviewed apply/conflict UX, remote↔local dependency reconstruction, outage recovery, bookmarks or stronger transaction guarantees across paged content snapshots, and two-independent-device convergence.
- Never start automatic replication on production data merely because this read-only operation is deployed.

See [S1](RUST_CLOUDFLARE_SYNC_S1.md), [S2](RUST_CLOUDFLARE_SYNC_S2.md), and [ADR 0005](../adr/0005-rust-cloudflare-sync.md).
