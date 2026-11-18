# SHIORI S3 — Offline metadata-only identity review

**Alpha implementation, 18 November 2026.** This is a *report*, not synchronization or consent to upload. It makes no network requests, opens the existing S3 v2 pull journal read-only, and never opens the canonical Rust task SQLite database. It cannot verify ownership simply because two UUIDs match.

## Inputs

1. A **private binary local export** created by the Rust CLI's `bridge-manifest` subcommand. The export contains task IDs, revisions, status, update/deletion timestamps and dependency IDs, not titles or notes. It is not interchangeable with `bridge-dump`.
2. A **pre-existing private S3 v2 pull journal** containing a completed atomic remote baseline from `sync_pull_journal.py baseline`. It must be owner-controlled, regular and mode `0600`. The reviewer does not initiate a baseline or poll.

Generate the local export only on a trusted workstation, with the task database path you intend to inspect:

```bash
umask 077
mkdir -p "$HOME/.local/share/shiori"
cargo build --locked -p shiori-cli
target/debug/shiori-cli --database /path/to/your/tasks.sqlite3 bridge-manifest \
  > "$HOME/.local/share/shiori/s3-local-manifest.bin"
python3 cloudflare/shiori-mcp/scripts/sync_review.py \
  --local-manifest "$HOME/.local/share/shiori/s3-local-manifest.bin" \
  --journal "$HOME/.local/share/shiori/tasks.pull.sqlite3"
```

The **export command** uses the normal Rust store opening path, which may migrate an older local database; protect or copy legacy data before using it. The **review command itself** only reads existing files. Keep the local export private and remove it when it is no longer needed. No OAuth code or legacy bearer token is required for this offline report.

## What the report means

The output is JSON with **aggregate counts only**, such as local-only IDs, remote-only *at the staged baseline* IDs, IDs appearing on both sides **without proven origin**, version disagreements, tombstone/active disagreements, and dependency edge differences. It does not print IDs, notes, task bodies, or other contents. It refuses unrecognized binary framing, unsafe file permissions, invalid local ordering, missing baseline v2, digest mismatch, and unsafe checkpoints.

The staged baseline can be out of date. When the pull journal contains events after its baseline cutoff, the report explicitly flags `baseline_is_not_current_remote_when_deltas_exist`. An unfinished event page is flagged separately. Those events are **not automatically projected into the baseline**, because an event may not contain the current record's full metadata and may refer to later revisions.

`identity_review_required` is **always true**, `safe_to_apply` is **always false**, and `data_transfer_performed` is **always false**. Matching IDs are not source provenance. No task import, conflict resolution, edge mutation, tombstone application or two-device convergence is implemented here.


### Post-baseline delta impact (metadata-only S3 continuation)

After a staged baseline, the event journal may contain inserts, updates, deletions, hard purges and dependency changes. The offline review now validates only **durably checkpointed** events and reports counts of:

- Post-baseline insert, update, delete, purge and edge-change events.
- Distinct changed task IDs and dependency pairs; how many changed task IDs overlap the two local/baseline inventories, or were absent from the staged remote baseline.
- Possible delete-vs-active conflicts on local tasks, event-reported task revisions ahead of the staged remote baseline, and dependency endpoints absent from either original inventory.

These are **risk indicators, not reconstructed remote state**. Event rows contain no task title or notes, and the review prints only counts, never IDs. An affected dependency endpoint absent from the *staged* baseline may have been inserted legitimately after that snapshot. A delete event does not give permission to delete the corresponding local task, nor does a matching UUID authenticate its origin.

The review refuses malformed, unknown-kind, out-of-order or uncheckpointed events, with a maximum of **50,000** post-baseline events examined within one read-only database snapshot. It never polls Cloudflare, updates the event journal, or resolves conflicts. Safe application remains **disabled** even when every count is zero.

## Synthetic tests

```bash
python3 -m unittest -v tests/test_sync_review.py
```

Fixtures cover metadata-only counts, delete-vs-active and version disagreements, post-baseline event impact and malformed/uncheckpointed events, stale event cursors, baseline integrity, untrusted file permissions, wrong binary export type and unsafe schema/checkpoint states. The canonical task fixture is left untouched.

See [S3 change-feed guide](RUST_CLOUDFLARE_SYNC_S3.md), [Issue #72](https://github.com/cryogenized-spec/SHIORI-/issues/72), and [ADR 0005](../adr/0005-rust-cloudflare-sync.md).
