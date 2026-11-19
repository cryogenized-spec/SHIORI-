# SHIORI S4 — Owner-controlled remote record pull to isolated SQLite preview

**Alpha, 18 November 2026.** This is a real **read-only remote-to-local content transfer** into a distinct private local preview file, not a canonical Rust task write, not user-facing automatic sync, and not full offline multi-device convergence. The authoritative Rust `tasks.sqlite3` remains untouched.

Run on an owner-controlled Linux workstation with the S4 server deployed, a private `0600` owner bearer token file, and an intentionally selected remote task ID:

```bash
python3 cloudflare/shiori-mcp/scripts/sync_pull_preview.py \
  --task-id '<REMOTE-TASK-UUID>' \
  --token-file "$HOME/.local/share/shiori/owner-token" \
  --shadow "$HOME/.local/share/shiori/remote.pull-preview.sqlite3" \
  --confirm-read-content
```

Optional `--local-manifest /private/path/s3-local-manifest.bin` lets the report flag whether this ID is already in a separately exported local Rust manifest. This **does not** open `tasks.sqlite3`; the manifest is only an existing private metadata file.

The client makes a **single explicitly authorized content-bearing** `sync.record.snapshot.read` call with `include_content=true` and verifies its expected fields, record UUID, sorted/unique prerequisites, bounded note size, current revision and tombstone, S2 receipt metadata (where present), atomic-snapshot flags and SHA-256 observation fingerprint. The response contains the task title and notes; these are **persisted to the preview database only**. The JSON console report contains counts, booleans and revision numbers, never titles, notes, task IDs or hashes.

The preview path must end in `.pull-preview.sqlite3`; the client creates a new `0600` file with a dedicated schema identity and refuses symlinks, insecure existing files, unknown schema or a destination matching the supplied inputs. A second read of exactly the same digest is idempotent. A different remote digest for the same task ID is **not silently overwritten**: the operator must preserve the earlier preview and explicitly choose how to review the changed remote record. No task, edge, status, tombstone, due date or version is applied to the canonical Rust database; there is no unsafe “last write wins” shortcut.

**Important data-model limit:** Remote D1 task records currently expose only the common title/notes/project/status/priority fields, whereas canonical Rust Tasks additionally store due dates, estimates, assignees and completion timestamps. The S2 source receipt proves **historical** provenance but cannot guarantee current record lineage or restore missing canonical fields. A safe local apply requires explicit field-complete mapping, a version-pinned conflict choice, local backup and rollback. Until implemented, the script always reports `safe_to_apply=false` and `automatic_sync=false`.

This file contains private notes, so store it on a trusted device, keep it out of shared folders, and treat its deletion/backup according to the user's own retention choices. No real account or device content is accessed by synthetic tests.

Test with:

```bash
python3 -m unittest discover -s tests -p 'test_sync_pull_preview.py' -v
```
