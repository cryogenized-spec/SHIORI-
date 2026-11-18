#!/usr/bin/env python3
"""Explicit, single-owner S2 first-import pilot for *new* Rust tasks only.

No background sync. Pair, preview and apply are independent owner actions.
The preview transmits task IDs and SHA-256, never task text/notes; apply is
the only command that uploads task contents over HTTPS to Cloudflare.
A successful apply reads and validates a remote receipt before asking Rust to
acknowledge its local outbox event. Never use the OAuth approval code as a token.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

BASE = "https://shiori-mcp-alpha.cryogenized.workers.dev"
MAX_ENVELOPE_BYTES = 16000


class SyncPilotError(ValueError):
    pass


def private_file(path: Path) -> Path:
    path = path.expanduser()
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise SyncPilotError("Refusing non-private, non-regular or symlinked file: " + str(path))
    return path


def read_token(path: Path) -> str:
    token = private_file(path).read_text(encoding="utf-8").strip()
    if not token or len(token) > 240:
        raise SyncPilotError("Empty or invalid owner bearer token; use the private token file, not OAuth approval code")
    return token


def journal_state(journal_path: Path) -> tuple[str, sqlite3.Connection]:
    path = private_file(journal_path).resolve()
    db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        if version != 1:
            raise SyncPilotError("Unexpected local outbox version; refusing sync")
        row = db.execute("SELECT value FROM sync_meta WHERE key='device_id'").fetchone()
        if not row:
            raise SyncPilotError("Local device identity is missing")
        device_id = row[0]
        if str(UUID(device_id)) != device_id:
            raise SyncPilotError("Invalid or noncanonical local device ID")
        return device_id, db
    except Exception:
        db.close()
        raise


def pending_event(db: sqlite3.Connection, device_id: str, event_id: str) -> tuple[str, dict, str]:
    row = db.execute(
        "SELECT task_id,local_version,payload_json FROM sync_outbox "
        "WHERE event_id=? AND state='pending'",
        (event_id,),
    ).fetchone()
    if not row:
        raise SyncPilotError("Event does not exist in pending outbox")
    task_id, version, payload = row
    if version != 1 or str(UUID(task_id)) != task_id:
        raise SyncPilotError("S2 only imports a new canonical UUID at revision 1")
    if not isinstance(payload, str) or len(payload.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        raise SyncPilotError("S2 pilot refuses task snapshots over 16 KiB")
    envelope = json.loads(payload)
    if (not isinstance(envelope, dict) or envelope.get("schema_version") != 1
            or envelope.get("event_id") != event_id
            or envelope.get("origin_device_id") != device_id
            or envelope.get("workspace_id") != "personal"
            or envelope.get("depends_on") != []
            or not isinstance(envelope.get("task"), dict)
            or envelope["task"].get("id") != task_id
            or envelope["task"].get("version") != 1
            or envelope["task"].get("deleted_at") is not None
            or event_id != f"sync1:{device_id}:{task_id}:1"):
        raise SyncPilotError("Invalid or unsupported first-import task envelope")
    return payload, envelope, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def api_call(operation: str, token: str, args: dict) -> dict:
    body = json.dumps({"workspace_id": "personal", **args}, separators=(",", ":")).encode("utf-8")
    req = Request(
        BASE + "/api/v1/ops/" + operation,
        data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                 "User-Agent": "ShioriSyncImportPilot/0.1"},
    )
    try:
        with urlopen(req, timeout=30) as response:
            reply = json.load(response)
    except HTTPError as exc:
        raise SyncPilotError(f"Cloud import request rejected (HTTP {exc.code}; {operation})") from None
    except (URLError, TimeoutError) as exc:
        raise SyncPilotError(f"Cloud import request failed ({operation}; check connection and receipt before retrying)") from exc
    if not isinstance(reply, dict) or reply.get("ok") is not True or reply.get("operation_id") != operation:
        raise SyncPilotError("Unexpected remote import response; do not acknowledge the local event")
    data = reply.get("data")
    if not isinstance(data, dict):
        raise SyncPilotError("Invalid remote import receipt structure")
    return data


def verify_receipt(receipt: dict, event_id: str, task_id: str, digest: str) -> None:
    if (receipt.get("source_event_id") != event_id
            or receipt.get("resource_id") != task_id
            or receipt.get("source_version") != 1
            or receipt.get("remote_revision") != 1
            or receipt.get("source_payload_sha256") != digest
            or receipt.get("remote_modified") is not False
            or not isinstance(receipt.get("receipt_id"), str)):
        raise SyncPilotError("Remote receipt is inconsistent, stale or incomplete; local event remains pending")
    if str(UUID(receipt["receipt_id"])) != receipt["receipt_id"]:
        raise SyncPilotError("Malformed remote receipt identity")


def acknowledge_local(cli: Path, canonical_db: Path, journal: Path,
                      event_id: str, task_id: str, revision: int) -> str:
    if not canonical_db.is_file():
        raise SyncPilotError("Canonical local database is missing; verified remote receipt remains recoverable")
    args = [
        str(cli), "--database", str(canonical_db),
        "sync-ack", event_id, "--remote-id", task_id,
        "--remote-revision", str(revision),
        "--local-task-id", task_id, "--local-revision", "1",
        "--journal", str(journal),
    ]
    try:
        result = subprocess.run(args, text=True, capture_output=True, timeout=30, check=True)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise SyncPilotError(
            "Remote receipt verified, but Rust local acknowledgement failed. "
            "Do not re-import with a new proposal; retry the same apply command."
        ) from exc
    if "acknowledged" not in result.stdout.lower():
        raise SyncPilotError("Unexpected local acknowledgement response; inspect sync-queue")
    return result.stdout.strip()


def run(args: argparse.Namespace) -> int:
    device_id, db = journal_state(args.journal)
    try:
        if args.action == "device":
            print("Local owner device:", device_id, "(no network request)")
            return 0

        if args.token_file is None:
            raise SyncPilotError("--token-file is required for network operations")
        token = read_token(args.token_file)
        if args.action == "pair":
            if not args.confirm_pairing:
                raise SyncPilotError("Pairing requires --confirm-pairing")
            data = api_call("sync.device.pair", token, {
                "device_id": device_id, "confirm_pairing": True,
                "idempotency_key": "s2pair-" + device_id,
            })
            if data.get("device_id") != device_id:
                raise SyncPilotError("Paired device ID did not match local identity")
            print("Owner device paired:", device_id)
            return 0

        payload, envelope, digest = pending_event(db, device_id, args.event_id)
        task_id = envelope["task"]["id"]
        if args.action == "preview":
            data = api_call("sync.import.preview", token, {
                "device_id": device_id, "task_id": task_id,
                "event_id": args.event_id, "local_version": 1,
                "payload_sha256": digest,
                "idempotency_key": "s2preview-" + str(uuid4()),
            })
            if data.get("task_id") != task_id or data.get("local_version") != 1:
                raise SyncPilotError("Cloud preview identity or version mismatch")
            print("Content-free preview accepted. No task contents uploaded.")
            print("Task ID:", task_id)
            print("SHA-256:", digest)
            print("Proposal:", data.get("proposal_id"))
            print("Expires:", data.get("expires_at"))
            print("Review the local task using shiori-cli show before explicitly applying.")
            return 0

        if args.action == "apply":
            if not args.confirm_import:
                raise SyncPilotError("Applying the task requires --confirm-import")
            proposal_id = str(UUID(args.proposal_id))
            if proposal_id != args.proposal_id:
                raise SyncPilotError("Proposal ID is not canonical")
            reply = api_call("sync.import.apply", token, {
                "proposal_id": proposal_id, "payload_json": payload,
                "owner_approved": True, "idempotency_key": "s2apply-" + proposal_id,
            })
            if (reply.get("resource_id") != task_id
                    or reply.get("revision") != 1
                    or reply.get("source_event_id") != args.event_id
                    or reply.get("source_payload_sha256") != digest):
                raise SyncPilotError("Apply response did not match the staged event")
            receipt = api_call("sync.import.receipt.read", token, {"event_id": args.event_id})
            verify_receipt(receipt, args.event_id, task_id, digest)
            canonical_db = args.database
            if canonical_db is None:
                if not args.journal.name.endswith(".sync.sqlite3"):
                    raise SyncPilotError(
                        "Remote receipt verified; specify --database for custom journal location"
                    )
                canonical_db = args.journal.with_name(
                    args.journal.name.removesuffix(".sync.sqlite3") + ".sqlite3"
                )
            result = acknowledge_local(args.cli, canonical_db, args.journal,
                                       args.event_id, task_id, 1)
            print(result)
            print("One initial task imported, canonical ID preserved; no ongoing sync is active.")
            return 0
        raise SyncPilotError("Unsupported pilot command")
    finally:
        db.close()


def main() -> int:
    ap = argparse.ArgumentParser(description="Explicit S2 single-task, owner-approved import pilot")
    ap.add_argument("--journal", type=Path,
                    default=Path.home()/".local/share/shiori/tasks.sync.sqlite3")
    ap.add_argument("--database", type=Path, help="Canonical Rust SQLite database for verified acknowledgement")
    ap.add_argument("--cli", type=Path, default=Path("target/debug/shiori-cli"))
    ap.add_argument("--token-file", type=Path, help="Private Cloudflare owner bearer token file (NOT OAuth approval code)")
    sub = ap.add_subparsers(dest="action", required=True)
    sub.add_parser("device", help="Print local device ID, with no network")
    pair = sub.add_parser("pair", help="Approve this specific local device")
    pair.add_argument("--confirm-pairing", action="store_true")
    preview = sub.add_parser("preview", help="Read-only content-free preview (writes only proposal metadata remotely)")
    preview.add_argument("event_id")
    apply = sub.add_parser("apply", help="Explicitly import one verified new task")
    apply.add_argument("event_id")
    apply.add_argument("--proposal-id", required=True)
    apply.add_argument("--confirm-import", action="store_true")
    args = ap.parse_args()
    try:
        return run(args)
    except (SyncPilotError, ValueError, sqlite3.Error, OSError, json.JSONDecodeError) as exc:
        print("Shiori S2 pilot:", str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
