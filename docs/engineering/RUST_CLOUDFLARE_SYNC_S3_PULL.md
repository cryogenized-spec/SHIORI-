# SHIORI S3 local metadata inbox — no task application

**Experimental, manual-only.** `sync_pull_journal.py` is an owner-initiated, *read-only remote* client for the S3 `sync.changes.read` operation. It stores remote change **metadata**, never titles, notes or attachments, in a separate private SQLite file. It neither opens nor modifies Rust's canonical `tasks.sqlite3`.

The remote change feed (PR #69) must be deployed before the `poll` command works. The initial baseline requirement remains mandatory: events recorded after D1 trigger installation are **not** a historical copy of the eight existing remote demo tasks.

## Usage

```bash
PULL=cloudflare/shiori-mcp/scripts/sync_pull_journal.py
python3 "$PULL" status
```

By default the isolated inbox is `~/.local/share/shiori/tasks.pull.sqlite3`; the parent directory must already exist. The script creates the journal at `0600`, refuses symlinks and world-readable files, unknown schema versions and unrelated SQLite files. Stored rows contain task UUIDs, event types and sequence numbers only, so they should still be treated as private metadata.

To fetch at most five bounded pages **only after** supplying your private, already existing *legacy owner bearer token file*:

```bash
python3 "$PULL" --token-file /private/path/to/owner-bearer-token.txt \
  --max-pages 5 poll
python3 "$PULL" status
```

**Do not substitute the Shiori OAuth owner approval code for the bearer token** or paste either value into chat, GitHub or logs. The poll operation never sends local task IDs or notes. It does not call `sync.import.apply` or any mutation endpoint. It also never confirms that local Rust tasks and remote D1 are synchronized.

## Recoverability guarantees

Each validated page of events is inserted and its checkpoint advanced in one local SQLite transaction. A power loss or network error may repeat an uncommitted page but cannot silently advance the cursor past unpersisted events. A fixed `cutoff` survives an interrupted multipage scan; a later poll resumes the same high-water range before taking a fresh cutoff.

If the remote server reports `baseline_required=false`, `local_rust_sync=true`, unexpected private content, missing or duplicate sequences, a changed cutoff, malformed continuation, excessive rows or workspace mismatch, the client refuses the page. It does **not** modify the canonical SQLite task file or attempt last-write-wins reconciliation.

The journal is deliberately capped at 50,000 events until we implement a reviewed compaction/acknowledgement protocol. Event sequences may have gaps because D1 IDs are globally increasing across workspaces, while this account receives only authorized workspace events.

The next milestone is a verified initial snapshot+cutoff, read-only local/cloud comparison and explicit conflict review; only then could we consider an opt-in, reversible apply to canonical Rust records.
