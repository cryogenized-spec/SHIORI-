#!/usr/bin/env python3
"""S9: attest ONE completed S8 local apply and persist privacy-safe revision map.

A checkpoint records metadata for later reconciliations but NEVER applies task
data. This is a separately confirmed, owner-authenticated write of a private
metadata-only SQLite file, NOT an automatic background sync loop.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys

import sync_apply_owner as owner
import sync_import_pilot as pilot
import sync_local_reconcile as recon
import sync_provenance_check as provenance
import sync_review as review

MAGIC = "shiori-s9-revision-checkpoint-v1"
LOCAL_ONLY = ("due_on", "estimate_minutes", "assignee_id", "created_at")


class CheckpointError(ValueError):
    pass


def _checkpoint_file(path: Path, sources: list[Path]) -> Path:
    if not path.name.endswith(".sync-checkpoint.sqlite3"):
        raise CheckpointError("Use a dedicated *.sync-checkpoint.sqlite3 destination")
    candidate = path.expanduser().absolute()
    parent = candidate.parent.resolve(strict=True)
    candidate = parent / candidate.name
    if not parent.is_dir() or candidate in sources:
        raise CheckpointError("Invalid or aliased checkpoint destination")
    if candidate.exists() or candidate.is_symlink():
        item = candidate.lstat()
        if not stat.S_ISREG(item.st_mode) or item.st_mode & 0o077:
            raise CheckpointError("Existing checkpoint must be a private 0600 regular file")
        if any(os.stat(candidate).st_ino == os.stat(p).st_ino and
               os.stat(candidate).st_dev == os.stat(p).st_dev for p in sources):
            raise CheckpointError("Checkpoint aliases an existing task or token file")
    return candidate


def _common_hash(record: dict) -> str:
    raw = json.dumps(
        {key: record[key] for key in owner.SOURCE_COMMON},
        ensure_ascii=False, separators=(",", ":")
    ).encode("utf8")
    return hashlib.sha256(raw).hexdigest()


def _checkpoint_row(canonical: Path, backup: Path, shadow: Path,
                    outbox: Path, token_file: Path,
                    task_id: str, event_id: str) -> dict:
    canonical, backup, shadow, outbox, token_file = recon._distinct_paths(
        [canonical, backup, shadow, outbox, token_file]
    )
    if not backup.name.endswith(".shiori-backup.sqlite3"):
        raise CheckpointError("Evidence must include the original private S7/S8 backup")
    with closing(recon._read_only(backup)) as db:
        db.execute("PRAGMA query_only=ON")
        integrity = db.execute("PRAGMA quick_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise CheckpointError("Pre-apply backup has invalid SQLite integrity")
    recon._source_check(outbox, recon._preview_snapshot(shadow, task_id),
                        task_id, event_id)
    original, source_hash = owner._original_source(outbox, task_id, event_id)
    before, edges_before = recon._local_view(backup, task_id)
    after, edges_after = recon._local_view(canonical, task_id)
    if before is None or after is None:
        raise CheckpointError("Canonical/backup task identity missing")
    staged = recon._preview_snapshot(shadow, task_id)
    if (before["deleted_at"] is not None or after["deleted_at"] is not None
            or staged["record"]["deleted_at"] is not None):
        raise CheckpointError("Tombstoned task cannot acquire a revision map")
    if (after["version"] != before["version"] + 1 or
            any(before[key] != original[key] for key in owner.SOURCE_COMMON)):
        raise CheckpointError("Pre-apply backup does not match original S2 baseline")
    if (edges_before != edges_after or edges_after != staged["depends_on"] or
            any(after[key] != staged["record"][key] for key in owner.SOURCE_COMMON)):
        raise CheckpointError("Current local task does not match approved remote common fields/graph")
    if any(before[key] != after[key] for key in LOCAL_ONLY):
        raise CheckpointError("S8 projection unexpectedly altered Rust-only task fields")
    live = owner._authenticated_current(
        token_file, event_id, task_id, source_hash, staged
    )
    if live["depends_on"] != edges_after:
        raise CheckpointError("Live remote graph changed after S8 apply")
    return {
        "task_id": task_id,
        "event_id": event_id,
        "source_payload_sha256": source_hash,
        "remote_record_sha256": live["record_sha256"],
        "remote_version": live["record"]["version"],
        "local_version": after["version"],
        "local_common_sha256": _common_hash(after),
        "remote_change_cutoff": live["cutoff"],
    }


def record(path: Path, row: dict) -> bool:
    """Create metadata-only, never replacing a different observed mapping."""
    created = False
    if not path.exists():
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                     getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(fd)
        created = True
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=rw", uri=True)) as db:
            db.execute("PRAGMA busy_timeout=4000")
            if created:
                db.executescript("""
                    CREATE TABLE checkpoint_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    CREATE TABLE checkpoints (
                        task_id TEXT PRIMARY KEY,
                        event_id TEXT NOT NULL, source_payload_sha256 TEXT NOT NULL,
                        remote_record_sha256 TEXT NOT NULL,
                        remote_version INTEGER NOT NULL, local_version INTEGER NOT NULL,
                        local_common_sha256 TEXT NOT NULL,
                        remote_change_cutoff INTEGER NOT NULL,
                        saved_at TEXT NOT NULL
                    );
                    PRAGMA user_version=1;
                """)
                db.execute("INSERT INTO checkpoint_meta VALUES('kind',?)", (MAGIC,))
                db.commit()
            version = db.execute("PRAGMA user_version").fetchone()
            kind = db.execute(
                "SELECT value FROM checkpoint_meta WHERE key='kind'"
            ).fetchone()
            if version is None or version[0] != 1 or kind is None or kind[0] != MAGIC:
                raise CheckpointError("Unrecognized or outdated revision checkpoint schema")
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT event_id,source_payload_sha256,remote_record_sha256,"
                "remote_version,local_version,local_common_sha256,remote_change_cutoff "
                "FROM checkpoints WHERE task_id=?", (row["task_id"],)
            ).fetchone()
            fields = (
                "event_id", "source_payload_sha256", "remote_record_sha256",
                "remote_version", "local_version", "local_common_sha256",
                "remote_change_cutoff",
            )
            new = tuple(row[k] for k in fields)
            if old:
                if old != new:
                    raise CheckpointError(
                        "A different mapping exists; manual revision conflict review required"
                    )
                db.rollback()
                return False
            db.execute(
                "INSERT INTO checkpoints VALUES(?,?,?,?,?,?,?,?,?)",
                (row["task_id"], *new, datetime.now(timezone.utc).isoformat())
            )
            db.commit()
        return True
    except (OSError, sqlite3.Error, CheckpointError) as exc:
        if created:
            # Only remove a file exclusively created by this call.
            try:
                path.unlink()
            except OSError:
                pass
        if isinstance(exc, CheckpointError):
            raise
        raise CheckpointError("Private checkpoint unavailable; canonical tasks unchanged") from exc


def stage(canonical: Path, backup: Path, shadow: Path,
          outbox: Path, token_file: Path, checkpoint: Path,
          task_id: str, event_id: str, *, owner_confirmed: bool) -> dict:
    if not owner_confirmed:
        raise CheckpointError("Explicit --confirm-checkpoint is required")
    if not provenance.canonical_uuid(task_id):
        raise CheckpointError("Choose one original canonical task UUID")
    inputs = recon._distinct_paths(
        [canonical, backup, shadow, outbox, token_file]
    )
    target = _checkpoint_file(checkpoint, inputs)
    row = _checkpoint_row(
        canonical, backup, shadow, outbox, token_file, task_id, event_id
    )
    changed = record(target, row)
    return {
        "checkpoint_recorded": changed,
        "same_checkpoint_idempotent": not changed,
        "local_revision": row["local_version"],
        "remote_revision_at_read": row["remote_version"],
        "cloud_observation_verified_at_read": True,
        "original_s2_provenance_verified": True,
        "common_field_digest_recorded": True,
        "canonical_rust_database_modified": False,
        "cloudflare_database_modified": False,
        "automatic_sync": False,
        "continuous_two_way_sync": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Explicit S9 source-checked post-apply revision checkpoint"
    )
    for arg in ("canonical", "backup", "shadow", "outbox", "token_file",
                "checkpoint"):
        ap.add_argument("--" + arg.replace("_", "-"), type=Path, required=True)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--event-id", required=True)
    ap.add_argument("--confirm-checkpoint", action="store_true")
    args = ap.parse_args()
    try:
        result = stage(
            args.canonical, args.backup, args.shadow, args.outbox,
            args.token_file, args.checkpoint, args.task_id, args.event_id,
            owner_confirmed=args.confirm_checkpoint,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (CheckpointError, pilot.SyncPilotError, provenance.ProvenanceError,
            recon.ReconciliationError, review.ReviewError, sqlite3.Error,
            OSError, ValueError):
        print(
            "SHIORI S9: checkpoint source, privacy or freshness verification failed; "
            "canonical task not changed", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
