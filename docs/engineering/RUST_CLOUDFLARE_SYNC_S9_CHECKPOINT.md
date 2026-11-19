# SHIORI S9 — Explicit post-apply revision checkpoint

S9 is an owner-invoked, metadata-only proof that one previous S8 cloud-to-Rust task application finished coherently. It records a durable, private pairing of local and cloud revisions, which a later conflict-aware sync loop can use. **S9 does not perform task writes, restore backups, upload content or enable background synchronization.**

Run only after the approved S8 local apply has completed, while the exact original private S7 backup and S4 staged remote observation are still available:

```bash
python3 cloudflare/shiori-mcp/scripts/sync_revision_checkpoint.py \
  --canonical "$HOME/.local/share/shiori/tasks.sqlite3" \
  --backup "$HOME/.local/share/shiori/pre-apply-unique.shiori-backup.sqlite3" \
  --shadow "$HOME/.local/share/shiori/remote.pull-preview.sqlite3" \
  --outbox "$HOME/.local/share/shiori/tasks.sync.sqlite3" \
  --token-file "$HOME/.local/share/shiori/owner-token" \
  --checkpoint "$HOME/.local/share/shiori/device.sync-checkpoint.sqlite3" \
  --task-id '<ORIGINAL-TASK-UUID>' \
  --event-id 'sync1:<DEVICE-UUID>:<ORIGINAL-TASK-UUID>:1' \
  --confirm-checkpoint
```

S9 opens the canonical Rust task, original private backup, S4 selected snapshot, and acknowledged S2 journal strictly in read-only mode. It refuses symlinks, insecure 0600 files, aliases and unknown schemas, verifies backup SQLite integrity, confirms that the backup task still matches the immutable S2 initial common fields, and checks that the post-S8 canonical record advanced exactly **one local revision** and now matches the approved staged S4 common fields. The dependency graph must be unchanged, and due date, effort estimate, assignee and creation timestamp must survive the local apply.

It then makes fresh **owner-authenticated receipt and atomic S4 record reads**, requiring the current cloud snapshot to still match the staged observation and original S2 source. A cloud change after S8 means the checkpoint is refused and the operator must reconcile again; this prevents recording a false completed revision mapping.

The result is persisted to a dedicated `*.sync-checkpoint.sqlite3` file created 0600 using exclusive create. The checkpoint stores task and source event IDs, original source and current record SHA-256, local/common field SHA-256, local and remote version numbers, observed remote change-feed cutoff, and timestamp — **never task titles, notes, token data or full task JSON**. Repeating exactly the same witness is idempotent; a new witness for the same task will be refused pending future conflict/revision migration support. It does not overwrite an existing checkpoint file or change the canonical task.

S9 is intentionally separate from S8: if a process crashes after S8's canonical write but before recording the checkpoint, the write survives and the missing checkpoint cannot be mistaken for a known synced revision. Operators must inspect the backup and task revision before recovering that state. An exact checkpoint proves historical witnessed state, **not a distributed lock** or current freshness indefinitely.

CI uses synthetic SQLite-only task fixtures and mocked HTTPS reads. No connected account tasks or real S2 payloads are contacted by tests. Run `python3 -m unittest discover -s tests -p 'test_sync_revision_checkpoint.py' -v`.

Next: reuse this durable map as the *base* for a three-way incremental merge of later edits, with guarded checkpoint transitions and explicit local/remote CAS. Physical two-device convergence and rollback remain required.
