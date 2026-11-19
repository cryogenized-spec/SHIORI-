# SHIORI S7 — Private, verified canonical Rust database backup

This is the mandatory local safety prerequisite before any future owner-approved S4/S6 cloud-to-Rust task write-back. The command does **not** read or contact Cloudflare, import tasks or run automatically. It creates **one new, private SQLite database copy** containing the user's task titles, notes, timestamps, attachments recorded in SQLite and dependencies.

```bash
shiori --database "$HOME/.local/share/shiori/tasks.sqlite3" \
  sync-backup \
  --to "$HOME/.local/share/shiori/before-sync-2026-11-19.shiori-backup.sqlite3" \
  --confirm-private-copy
```

The destination must be a new filename ending in `.shiori-backup.sqlite3`, in an existing writable directory. It cannot point to the canonical database. Existing backups and symlinks are never overwritten, and on Unix the new destination is created `0600` using an exclusive create. A noninteractive/batch call without `--confirm-private-copy` fails without creating a file.

SHIORI uses SQLite's `VACUUM INTO` through the **existing Rust SQLite connection** to take a coherent snapshot instead of copying a live WAL-mode file. On completion, it opens the new file read-only, requires `PRAGMA quick_check = 'ok'`, requires canonical schema version 3 and compares task row counts. It removes only a newly created, unverified copy if verification fails; it never deletes, edits or truncates the original.

This is a private-data copy, not a remote upload. The generated file should stay on an owner-controlled device with suitable disk encryption, secure folder permissions and retention appropriate to the user's preference. The CLI prints only a success sentence, not customer/task data or a token.

**Remaining release gates:** The backup alone cannot verify S2 identity, authenticated freshness, version mapping or conflict resolution. User-authorized local apply must validate S6 preflight plus an immediate live S4 re-read, commit expected local revision and audit the result, and offer an explicit restore path. Existing `local_rust_sync=false` remains accurate.

Synthetic Rust tests cover consent, private file permissions, consistent source preservation after later edits, existing destination refusal, invalid filenames, symlinks and in-memory databases. No real local databases are opened by CI.
