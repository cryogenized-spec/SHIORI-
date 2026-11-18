# SHIORI S3 — Receipt-aware, read-only reconciliation review

**Experimental owner-only tooling, 18 November 2026.** This ties one **previously authenticated, acknowledged S2 import receipt** to the local Rust task ID and the same ID in an existing staged Cloudflare D1 baseline. It does not download or synchronize task content, grant write authority, or prove that a currently stored record has not been deleted and re-created.

The earlier [offline S3 counts review](RUST_CLOUDFLARE_SYNC_S3_REVIEW.md) deliberately treats every shared UUID as unverified. The [single-event provenance verifier](RUST_CLOUDFLARE_SYNC_S3_PROVENANCE.md) can authenticate an original approved import receipt, but cannot locate that task in the broader two-database inventory. This new script composes those two guarantees without treating them as stronger than they are.

## Run on one acknowledged synthetic task

Prepare a private `bridge-manifest` binary export using `shiori-cli`, a private S3 v2 pull journal containing an atomic D1 baseline, and the S1/S2 Rust `tasks.sync.sqlite3` outbox containing an **already acknowledged** first-import event for a task that appears in both inventories. The owner token file must be private; the OAuth approval code is not a bearer token.

```bash
python3 cloudflare/shiori-mcp/scripts/sync_receipt_review.py \
  --local-manifest /private/path/s3-local-manifest.bin \
  --pull-journal /private/path/tasks.pull.sqlite3 \
  --outbox /private/path/tasks.sync.sqlite3 \
  --token-file /private/path/shiori-owner-token.txt \
  --event-id 'sync1:<DEVICE-UUID>:<TASK-UUID>:1'
```

The script first validates the private local files (`0600` regular files, no symlinks), the manifest framing, local outbox acknowledged state, and the remote baseline's atomic digest and event checkpoint. If the selected S2 task is absent from **either** staged inventory, it refuses the operation *before* connecting to Cloudflare.

Only after these checks does it issue one owner-authenticated `sync.import.receipt.read` request containing **only the selected event ID**. It validates the returned receipt ID, source identity and original payload hash against the locally staged S2 envelope. It never sends the original payload, notes, title or manifest. It never opens the canonical Rust `tasks.sqlite3` database.

## Result interpretation

The JSON reports aggregate local/remote inventories, pending post-baseline change counts, one **historically attested shared import** and how many other shared IDs lack any authenticated S2 receipt. It flags whether this imported task has a later local revision or tombstone, remote baseline revision/tombstone differences, later remote task changes, later remote dependency changes and delete/purge events.

**An authenticated historical import is not a cryptographic device identity, a current content snapshot or a valid apply instruction.** Even if every revision is 1 and there are no later events, local/cloud current content equivalence is **unverified**. Remote records may have been changed between snapshots; events cannot fully reconstruct task content; purged IDs may require a stronger lineage check. Both `current_record_provenance_verified` and `current_task_content_equivalence_verified` remain `false`, and `safe_to_apply` remains `false`. The full local-only and remote-only aggregates remain unchanged; no candidate disappears from review merely because one S2 receipt was attested.

The script does not write a proof cache, local journal, task database or Cloudflare record. It emits **no task IDs, event IDs, payload hashes, token, titles or notes**; only aggregate counts and revision metadata. An unavailable receipt or missing network connection fails with no mutation.

## Synthetic tests

```bash
python3 -m unittest discover -s tests -p 'test_sync_receipt_review.py' -v
```

Eleven isolated tests cover original-source overlap, later task/dependency events, remote delete, local revision/tombstone disagreement, source absence on either side, missing acknowledgements, corrupt staged baseline, insecure files, forged receipts and failed HTTPS. The canonical task fixture is never opened or changed.

See [issue #72](https://github.com/cryogenized-spec/SHIORI-/issues/72) and [issue #47](https://github.com/cryogenized-spec/SHIORI-/issues/47). The next necessary steps remain current-record lineage/authenticated snapshots, explicit conflict UX, deletion/re-creation handling and a real two-device offline convergence test.
