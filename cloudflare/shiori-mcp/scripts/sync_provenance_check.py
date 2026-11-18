#!/usr/bin/env python3
"""Verify provenance of ONE acknowledged S2 import against an authenticated remote receipt.

Read-only inspection of a private Rust outbox plus an owner-authenticated
metadata-only HTTPS receipt. No task content is sent, fetched, or displayed.
Never opens canonical tasks.sqlite3 or changes any local/cloud records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from uuid import UUID

import sync_import_pilot as pilot

RECEIPT_FIELDS = {
    "receipt_id", "resource_id", "source_event_id", "source_version",
    "remote_revision", "source_payload_sha256", "remote_modified",
}


class ProvenanceError(ValueError):
    pass


def canonical_uuid(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 36:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def acknowledged_source(db: sqlite3.Connection, device_id: str,
                        event_id: str) -> tuple[str, str]:
    """Locally hash the original immutable native payload, never upload it."""
    if not isinstance(event_id, str) or not 8 <= len(event_id) <= 160:
        raise ProvenanceError("Invalid event identifier")
    row = db.execute(
        "SELECT task_id,local_version,payload_json,state,remote_id,remote_version "
        "FROM sync_outbox WHERE event_id=?", (event_id,)
    ).fetchone()
    if row is None:
        raise ProvenanceError("Import event not found in the local outbox")
    task_id, version, payload, state, remote_id, remote_version = row
    if state != "acknowledged":
        raise ProvenanceError("Only previously acknowledged S2 imports qualify for attestation")
    if (not canonical_uuid(device_id) or not canonical_uuid(task_id)
            or event_id != f"sync1:{device_id}:{task_id}:1"
            or type(version) is not int or version != 1
            or remote_id != task_id or type(remote_version) is not int
            or remote_version != 1):
        raise ProvenanceError("Local acknowledgement identities or revisions disagree")
    if (not isinstance(payload, str)
            or len(payload.encode("utf-8")) > pilot.MAX_ENVELOPE_BYTES):
        raise ProvenanceError("Invalid or oversized local source snapshot")
    try:
        envelope = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise ProvenanceError("Local S2 snapshot is not valid JSON") from exc
    if (not isinstance(envelope, dict) or envelope.get("schema_version") != 1
            or envelope.get("event_id") != event_id
            or envelope.get("origin_device_id") != device_id
            or envelope.get("workspace_id") != "personal"
            or envelope.get("depends_on") != []
            or not isinstance(envelope.get("task"), dict)
            or envelope["task"].get("id") != task_id
            or type(envelope["task"].get("version")) is not int
            or envelope["task"]["version"] != 1
            or envelope["task"].get("deleted_at") is not None):
        raise ProvenanceError("Local source envelope is not the supported S2 first import")
    return task_id, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def attest_receipt(receipt: object, event_id: str,
                   task_id: str, source_hash: str) -> dict:
    """An authenticated D1 import receipt proves origin, not current equivalence."""
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise ProvenanceError("Unexpected remote receipt fields (possible content leak)")
    if (not canonical_uuid(receipt["receipt_id"])
            or receipt["resource_id"] != task_id
            or receipt["source_event_id"] != event_id
            or type(receipt["source_version"]) is not int
            or receipt["source_version"] != 1
            or receipt["source_payload_sha256"] != source_hash
            or type(receipt["remote_revision"]) is not int
            or not 1 <= receipt["remote_revision"] <= 2**53 - 1
            or type(receipt["remote_modified"]) is not bool
            or receipt["remote_modified"] != (receipt["remote_revision"] != 1)):
        raise ProvenanceError("Remote import receipt does not attest this local source")
    return {
        "s2_source_provenance_confirmed": True,
        "source_revision": 1,
        "remote_observed_revision": receipt["remote_revision"],
        "remote_modified_since_import": receipt["remote_modified"],
        "local_outbox_state": "acknowledged",
        "other_task_identities_unverified": True,
        "local_rust_sync": False,
        "safe_to_apply": False,
        "task_content_transferred": False,
        "local_or_remote_task_writes": False,
    }


def verify(journal: Path, token_file: Path, event_id: str) -> dict:
    device_id, db = pilot.journal_state(journal)
    try:
        # Never send the local payload, even to an authenticated server.
        task_id, digest = acknowledged_source(db, device_id, event_id)
    finally:
        db.close()
    token = pilot.read_token(token_file)
    receipt = pilot.api_call("sync.import.receipt.read", token, {"event_id": event_id})
    return attest_receipt(receipt, event_id, task_id, digest)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Owner-authenticated, read-only S2 source receipt verification")
    parser.add_argument("--journal", type=Path, required=True,
                        help="Private existing Rust outbox (tasks.sync.sqlite3)")
    parser.add_argument("--token-file", type=Path, required=True,
                        help="Private legacy owner bearer (NOT OAuth approval code)")
    parser.add_argument("--event-id", required=True, help="One explicitly selected S2 sync1:... event")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.journal, args.token_file, args.event_id),
                         indent=2, sort_keys=True))
        return 0
    except (ProvenanceError, pilot.SyncPilotError, sqlite3.Error, OSError,
            ValueError) as exc:
        # Neither server response body nor token nor private payload is logged.
        print("SHIORI S3 receipt verification: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
