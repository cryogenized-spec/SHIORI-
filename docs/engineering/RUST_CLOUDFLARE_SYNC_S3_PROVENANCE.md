# SHIORI S3 — Read-only first-import provenance verification

**Alpha; 18 November 2026.** A matching task UUID or title does not establish that local Rust/SQLite and remote Cloudflare D1 refer to the same original task. This explicit, single-event check uses the existing S2 reviewed-first-import receipt, which can attest the identity and exact source payload of an **already acknowledged** S2 task import. It does not synchronize databases.

## How to run

Use a local Rust `tasks.sync.sqlite3` S1 outbox where a synthetic revision-1 S2 import has already been successfully approved, applied and acknowledged. Obtain the event ID from `shiori-cli sync-queue`. Use a private, owner-controlled **legacy bearer token file**; it is not the OAuth approval code.

```bash
python3 cloudflare/shiori-mcp/scripts/sync_provenance_check.py \
  --journal /private/path/to/tasks.sync.sqlite3 \
  --token-file /private/path/to/shiori-owner-token.txt \
  --event-id 'sync1:<DEVICE-UUID>:<TASK-UUID>:1'
```

Both local files must be ordinary, private mode `0600` files. The script opens the existing outbox in SQLite read-only mode. It checks that the record is acknowledged, its remote ID and revision-1 acknowledgement match the local task UUID, and its original immutable payload is a valid dependency-free revision-1 S2 task envelope. It computes **SHA-256 locally** over that original payload and sends **only the event ID** to the owner-authenticated `sync.import.receipt.read` endpoint.

The Cloudflare endpoint returns import receipt metadata — not task titles, notes or original JSON. The script requires an exact matching event ID, resource ID, original source revision, payload digest and valid receipt ID. A later remote revision is allowed as historical provenance evidence but is **flagged as modified since import**. The receipt does not certify that the current remote title, notes, status or dependencies match the local version; it is not an authorization to copy either version.

Successful output contains booleans and remote revision counts only. No task UUID, device UUID, raw payload, notes, title, hash or bearer token is printed. The tool never reads/writes the canonical `tasks.sqlite3`, cannot pair/revoke devices, never applies a task, and does not alter any local or remote records. Even with a verified S2 receipt, `safe_to_apply=false`, `local_rust_sync=false` and **other task identities remain unverified**.

If local acknowledgement is missing, the receipt is absent, stale or inconsistent, the remote credential is unauthorized, or the network is unavailable, the check fails without changing any data. Do not infer provenance for other tasks from one successful import.

## Synthetic tests

```bash
python3 -m unittest discover -s tests -p 'test_sync_provenance_check.py' -v
```

Nine isolated tests cover verified and subsequently modified receipts, tampering, private input permissions, absent acknowledgement, failed HTTPS, unexpected remote content, and the invariant that no canonical task data is touched. No live user tasks or secret tokens are used in tests.

See [S2 import protocol](RUST_CLOUDFLARE_SYNC_S2.md), [S3 baseline and feed](RUST_CLOUDFLARE_SYNC_S3.md), [offline metadata review](RUST_CLOUDFLARE_SYNC_S3_REVIEW.md), and [issue #72](https://github.com/cryogenized-spec/SHIORI-/issues/72). Full provenance across pre-existing remote tasks, historical deletes, cross-device revisions and dependency edits is **still unresolved**.
