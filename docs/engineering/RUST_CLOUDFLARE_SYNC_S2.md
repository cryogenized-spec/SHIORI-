# SHIORI S2 — Owner-reviewed first-import pilot

**Deployed single-owner alpha — 18 November 2026:** S2 first-import and the S3 paired-device status/revocation controls are live, with 31 remote MCP operations verified. This pilot is **not** bidirectional synchronization and is suitable only for owner-reviewed, disposable synthetic tasks; do not use production or customer data until full sync acceptance is verified.

## Narrow scope

S2 accepts exactly one *new*, *active*, *dependency-free* Rust task at **revision 1**. It preserves the canonical local UUID in remote D1. The initial transfer retains the entire native Jiff/SQLite task snapshot as source provenance, even though the remote task projection currently exposes fewer fields. It refuses existing IDs (including deleted tombstones), source revisions above 1, unresolved dependencies, unpaired devices, altered payload hashes, expired proposals and missing explicit owner approval.

**Nothing is uploaded automatically.** A local outbox entry is not a network transfer. The Cloudflare preview receives only owner device ID, task UUID, event ID, revision and SHA-256; it never receives title/notes. The final apply sends the task's full JSON including notes and project **only after the owner supplies the confirmation flag** and matching preview ID. An authenticated receipt is checked before marking the local queue entry acknowledged. Directly invoking `shiori-cli sync-ack` without first verifying a remote receipt is not an attested acknowledgement.

D1 adds independent `sync_devices`, `sync_import_previews` and `sync_imports` tables. No canonical D1 task is modified by the migration itself. `sync_imports.payload_json` retains potentially sensitive task content; remote access must remain scoped to the owner.

## Disposable synthetic-device exercise (after deployment)

Use a **synthetic, unconnected** local Rust SQLite database first. Replace example paths only with files you deliberately created.

```bash
cargo build --locked -p shiori-cli
# Create an isolated, owner-private temporary directory:
TESTDIR=$(mktemp -d)
target/debug/shiori-cli --database "$TESTDIR/tasks.sqlite3" add "[DUMMY] S2 import check"
target/debug/shiori-cli --database "$TESTDIR/tasks.sqlite3" list
# Determine the generated task UUID from the above command; do not guess it.
target/debug/shiori-cli --database "$TESTDIR/tasks.sqlite3" \
  sync-stage 'THE-TASK-UUID' --if-version 1
target/debug/shiori-cli --database "$TESTDIR/tasks.sqlite3" sync-queue
```

The CLI outbox is `$TESTDIR/tasks.sync.sqlite3` and is private (Unix `0600`). It contains actual staged task content, so use harmless fixture data.

The remaining commands require a **private legacy owner bearer token file** already authorized for the isolated Cloudflare alpha. This is **not** the Shiori OAuth approval code. Do not paste either secret into chat, issues, logs or GitHub.

```bash
PILOT=cloudflare/shiori-mcp/scripts/sync_import_pilot.py
JOURNAL="$TESTDIR/tasks.sync.sqlite3"
TOKEN=/private/path/to/owner-bearer-token.txt
# Protect the existing bearer file:
chmod 600 "$TOKEN"
python3 "$PILOT" --journal "$JOURNAL" device
python3 "$PILOT" --journal "$JOURNAL" --token-file "$TOKEN" \
  pair --confirm-pairing
python3 "$PILOT" --journal "$JOURNAL" --token-file "$TOKEN" \
  preview 'THE-SYNC1-EVENT-ID'
```

The preview prints a proposed ID and expiry. Review your local synthetic task and SHA-256 **before** approving the transfer. When explicitly ready to send its complete content:

```bash
python3 "$PILOT" --journal "$JOURNAL" \
  --database "$TESTDIR/tasks.sqlite3" \
  --token-file "$TOKEN" --cli target/debug/shiori-cli \
  apply 'THE-SYNC1-EVENT-ID' --proposal-id 'THE-PROPOSAL-UUID' \
  --confirm-import
```

The final step uses HTTPS, re-verifies the remote receipt's task ID/event ID/hash and expected revision, then runs the Rust local `sync-ack` command. If the remote committed but local acknowledgement failed, **retry the exact same apply with the same proposal ID**; do not generate a second proposal and risk a duplicate. If a remote edit has occurred in the meantime, verification refuses acknowledgement and preserves the pending local snapshot.

## Paired-device revocation (S3 owner control)

`sync.device.status.read` (`shiori_sync_device_status_read`) returns a device's pairing and revocation timestamps plus whether it can stage new imports. This is an authenticated metadata read, available to OAuth `mcp:read` clients.

`sync.device.revoke` (`shiori_sync_device_revoke`) requires the owner credential, `mcp:write` for OAuth clients, an exact paired device UUID, an idempotency key and **`confirm_revocation: true`**. Revocation is permanent for that device identity: the old UUID cannot be paired again. The server refuses subsequent import previews and applies even when an old, unexpired preview ID exists. Both mutation paths verify active pairing **inside their D1 write transactions**, not just in the earlier read.

Revocation does **not** delete any task, original native payload, import receipt, or local Rust journal. It does **not** revoke the OAuth user access token or legacy owner bearer token. To revoke a compromised authorization credential, also use the appropriate **separate credential-revocation/rotation workflow**. Revoking a device does not make an infected device safe, and device UUIDs alone are never cryptographic device authentication.

This is a single-owner alpha control, not secure multiple-user pairing. No background import or automatic synchronization is enabled.

## Security and recovery invariants

- Pairing requires the owner bearer credential and an explicit confirmation; a device UUID by itself is **not** an authentication secret.
- Preview tokens expire after 15 minutes. Different payloads cannot be applied under the original SHA-256.
- The first-import transaction must commit the remote task, complete native source JSON, receipt and idempotency marker together, or reject without replacing a pre-existing record.
- The local journal is crash-durable, owner-private and unaffected by cloud retries; the canonical local SQLite file is not rewritten by S2.
- Authenticated OAuth `mcp:read` may read a content-free receipt but **cannot** pair or apply an import; `mcp:write` is required for mutations.
- A matching UUID or title never proves a shared provenance for a pre-existing cloud record. A 409 conflict is **not** permission to overwrite.
- Real deletion propagation, dependency reconstruction, task revisions above 1, automatic conflict merging, attachment upload and true two-way convergence remain **not implemented**. The separate S3 device-revocation control is now live but does not authenticate a device cryptographically or rotate access tokens.

**Beta acceptance remains blocked** until two independent real clients demonstrate offline edit/reconnect conflict handling, tombstone safety, verified rollback and consistent canonical IDs. See [S1 foundation](RUST_CLOUDFLARE_SYNC_S1.md) and [ADR 0005](../adr/0005-rust-cloudflare-sync.md).
