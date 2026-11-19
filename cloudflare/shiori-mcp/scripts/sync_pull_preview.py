#!/usr/bin/env python3
"""Explicit owner-only S4 remote content pull into a *separate* private preview.

Does NOT open or mutate canonical Rust tasks.sqlite3 or any S1/S3 journal.
One owner-selected record, at most 16 KiB; never an automatic sync agent.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys

import sync_import_pilot as pilot
import sync_review as review

FIELDS = {
    "id", "title", "notes", "project", "status", "priority", "version",
    "created_at", "updated_at", "deleted_at",
}
IMPORT_FIELDS = {
    "receipt_id", "source_event_id", "source_version", "source_payload_sha256",
}
DATA_FIELDS = {
    "record", "depends_on", "source_import", "cutoff", "record_sha256",
    "consistent_snapshot", "local_rust_sync", "automatic_apply",
}
MAGIC = "shiori-s4-private-current-record-preview-v1"
MAX_OBSERVATION_BYTES = 16_384


class PullPreviewError(ValueError):
    pass


def validate_snapshot(data: object, task_id: str) -> dict:
    """Never print, automatically apply or trust unverified remote source."""
    if not isinstance(data, dict) or set(data) != DATA_FIELDS:
        raise PullPreviewError("Current-record response has unexpected fields")
    record = data["record"]
    if not isinstance(record, dict) or set(record) != FIELDS:
        raise PullPreviewError("Current-record body is missing expected fields")
    if not isinstance(task_id, str) or not 1 <= len(task_id) <= 160 or record["id"] != task_id:
        raise PullPreviewError("Current-record identity disagrees with requested task")
    if any(not isinstance(record[k], str) for k in
           ("id", "title", "notes", "project", "status", "priority", "created_at", "updated_at")):
        raise PullPreviewError("Current-record data has invalid field types")
    if record["deleted_at"] is not None and not isinstance(record["deleted_at"], str):
        raise PullPreviewError("Invalid remote tombstone")
    if (record["status"] not in ("todo", "in_progress", "done")
            or record["priority"] not in ("low", "medium", "high", "urgent")
            or type(record["version"]) is not int
            or not 1 <= record["version"] <= 2**53-1):
        raise PullPreviewError("Unexpected remote revision or task enum")
    depends = data["depends_on"]
    if (not isinstance(depends, list) or len(depends) > 200
            or any(not isinstance(value, str) or not value or len(value) > 160
                   or value == task_id for value in depends)
            or depends != sorted(set(depends))):
        raise PullPreviewError("Invalid prerequisite identities or ordering")
    origin = data["source_import"]
    if origin is not None and (
        not isinstance(origin, dict) or set(origin) != IMPORT_FIELDS
        or any(not isinstance(origin[k], str) for k in
               ("receipt_id", "source_event_id", "source_payload_sha256"))
        or len(origin["source_payload_sha256"]) != 64
        or type(origin["source_version"]) is not int or origin["source_version"] != 1
    ):
        raise PullPreviewError("Source receipt is malformed or unexpectedly content-bearing")
    if (type(data["cutoff"]) is not int or not 0 <= data["cutoff"] <= 2**53-1
            or data["consistent_snapshot"] is not True
            or data["local_rust_sync"] is not False
            or data["automatic_apply"] is not False):
        raise PullPreviewError("Remote snapshot lacks atomic read-only guarantees")
    evidence = {
        "record": record,
        "depends_on": depends,
        "source_import": origin,
        "cutoff": data["cutoff"],
    }
    raw = json.dumps(evidence, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_OBSERVATION_BYTES:
        raise PullPreviewError("Remote observation exceeds 16 KiB budget")
    digest = hashlib.sha256(raw).hexdigest()
    if data["record_sha256"] != digest:
        raise PullPreviewError("Current-record digest does not match content")
    return evidence


def private_shadow_path(path: Path, other: list[Path]) -> Path:
    """Require purpose-specific file, not a canonical task or journal path."""
    path = path.expanduser().absolute()
    if not path.name.endswith(".pull-preview.sqlite3"):
        raise PullPreviewError("Only a dedicated *.pull-preview.sqlite3 may receive task content")
    if path in {p.expanduser().absolute() for p in other}:
        raise PullPreviewError("Preview destination aliases an input file")
    if path.exists() or path.is_symlink():
        meta = path.lstat()
        if not stat.S_ISREG(meta.st_mode) or meta.st_mode & 0o077:
            raise PullPreviewError("Preview must be a private regular 0600 file, not a symlink")
    return path


def stage(path: Path, evidence: dict, digest: str) -> bool:
    """No overwrites: a changed remote revision must get a fresh review."""
    created = False
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        created = True
    con = sqlite3.connect("file:" + path.as_uri().removeprefix("file:") + "?mode=rw", uri=True)
    try:
        con.execute("PRAGMA busy_timeout=4000")
        if created:
            con.executescript("""
                CREATE TABLE preview_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE previews (
                    task_id TEXT PRIMARY KEY, digest TEXT NOT NULL,
                    observation_json TEXT NOT NULL, staged_at TEXT NOT NULL
                );
                PRAGMA user_version=1;
            """)
            con.execute("INSERT INTO preview_meta VALUES('kind',?)", (MAGIC,))
            con.commit()
        if con.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise PullPreviewError("Preview has unknown schema; refusing update")
        kind = con.execute(
            "SELECT value FROM preview_meta WHERE key='kind'"
        ).fetchone()
        if not kind or kind[0] != MAGIC:
            raise PullPreviewError("Not an S4 isolated preview database")
        con.execute("BEGIN IMMEDIATE")
        task_id = evidence["record"]["id"]
        old = con.execute("SELECT digest FROM previews WHERE task_id=?", (task_id,)).fetchone()
        if old:
            if old[0] != digest:
                raise PullPreviewError(
                    "Remote record differs from previously staged revision; no overwrite attempted"
                )
            con.rollback()
            return False
        con.execute(
            "INSERT INTO previews(task_id,digest,observation_json,staged_at) VALUES(?,?,?,?)",
            (task_id, digest, json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
             datetime.now(timezone.utc).isoformat())
        )
        con.commit()
        return True
    except (sqlite3.Error, OSError) as exc:
        con.rollback()
        raise PullPreviewError("Private preview is unavailable or invalid") from exc
    finally:
        con.close()


def pull(task_id: str, token_file: Path, shadow: Path,
         *, confirmed: bool, local_manifest: Path | None = None) -> dict:
    if not confirmed:
        raise PullPreviewError("A content-bearing remote read requires --confirm-read-content")
    if local_manifest is not None:
        local, _ = review.local_manifest(
            review.private_file_bytes(local_manifest, review.MAX_LOCAL_BYTES)
        )
        local_overlap = task_id in local
    else:
        local_overlap = None
    protected = private_shadow_path(
        shadow, [token_file] + ([local_manifest] if local_manifest is not None else [])
    )
    token = pilot.read_token(token_file)
    data = pilot.api_call("sync.record.snapshot.read", token, {
        "task_id": task_id, "include_content": True,
    })
    evidence = validate_snapshot(data, task_id)
    digest = data["record_sha256"]
    changed = stage(protected, evidence, digest)
    return {
        "private_preview_staged": changed,
        "repeat_read_idempotent": not changed,
        "remote_observed_revision": evidence["record"]["version"],
        "remote_tombstone_present": evidence["record"]["deleted_at"] is not None,
        "historical_s2_receipt_present": evidence["source_import"] is not None,
        "local_manifest_has_matching_id": local_overlap,
        "unknown_local_inventory": local_overlap is None,
        "source_lineage_unverified": True,
        "current_local_content_equivalence_unverified": True,
        "safe_to_apply": False,
        "canonical_rust_database_modified": False,
        "automatic_sync": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Explicit S4 private remote snapshot pull preview")
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--token-file", type=Path, required=True)
    ap.add_argument("--shadow", type=Path, required=True)
    ap.add_argument("--local-manifest", type=Path)
    ap.add_argument("--confirm-read-content", action="store_true")
    args = ap.parse_args()
    try:
        print(json.dumps(pull(
            args.task_id, args.token_file, args.shadow,
            confirmed=args.confirm_read_content, local_manifest=args.local_manifest,
        ), indent=2, sort_keys=True))
        return 0
    except (PullPreviewError, pilot.SyncPilotError, review.ReviewError,
            sqlite3.Error, OSError, ValueError) as exc:
        print("SHIORI S4 pull preview:", str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
