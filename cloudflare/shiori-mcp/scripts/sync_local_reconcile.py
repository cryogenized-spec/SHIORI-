#!/usr/bin/env python3
"""S6: offline source-bound Rust/D1 reconciliation of ONE selected task.

READ ONLY: does not open a writable SQLite handle, call Cloudflare, print
task contents, write a cache, or invoke the canonical Rust apply method.
A historical S2 outbox receipt is not proof of current remote freshness.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

import sync_import_pilot as pilot
import sync_provenance_check as provenance
import sync_pull_preview as preview
import sync_review as review

COMMON_FIELDS = ("title", "notes", "project", "status", "priority")
RUST_COLUMNS = (
    "id", "title", "notes", "project", "priority", "status", "due_on",
    "created_at", "updated_at", "completed_at", "version", "deleted_at",
    "estimate_minutes", "assignee_id",
)


class ReconciliationError(ValueError):
    """No user contents or identifiers may appear in the public error."""


def _private(path: Path) -> Path:
    review.private_file_bytes(path, 0, metadata_only=True)
    return path.expanduser().resolve(strict=True)


def _distinct_paths(paths: list[Path]) -> list[Path]:
    files = [_private(path) for path in paths]
    if len(set(files)) != len(files):
        raise ReconciliationError("One input aliases another private database")
    # Reject hard links too, without opening or mutating any database.
    import os
    identifiers = [(os.stat(path).st_dev, os.stat(path).st_ino) for path in files]
    if len(set(identifiers)) != len(identifiers):
        raise ReconciliationError("Private input databases share a file identity")
    return files


def _read_only(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=4)


def _preview_snapshot(shadow: Path, task_id: str) -> dict:
    if not shadow.name.endswith(".pull-preview.sqlite3"):
        raise ReconciliationError("Expected isolated S4 pull-preview, not a task database")
    with _read_only(shadow) as db:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone()[0] != 1:
            raise ReconciliationError("Unsupported S4 preview schema")
        kind = db.execute(
            "SELECT value FROM preview_meta WHERE key='kind'"
        ).fetchone()
        if kind is None or kind[0] != preview.MAGIC:
            raise ReconciliationError("Unrecognized isolated S4 preview")
        row = db.execute(
            "SELECT digest,observation_json FROM previews WHERE task_id=?",
            (task_id,),
        ).fetchone()
    if row is None:
        raise ReconciliationError("Selected task is not present in the S4 preview")
    stored_digest, raw = row
    if not isinstance(raw, str) or len(raw.encode("utf8")) > preview.MAX_OBSERVATION_BYTES:
        raise ReconciliationError("S4 preview content is missing or exceeds the size budget")
    try:
        evidence = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ReconciliationError("Invalid private S4 observation") from exc
    if not isinstance(evidence, dict) or set(evidence) != {
        "record", "depends_on", "source_import", "cutoff",
    }:
        raise ReconciliationError("Unexpected S4 observation fields")
    snapshot = {
        **evidence,
        "record_sha256": stored_digest,
        "consistent_snapshot": True,
        "local_rust_sync": False,
        "automatic_apply": False,
    }
    try:
        preview.validate_snapshot(snapshot, task_id)
    except preview.PullPreviewError as exc:
        raise ReconciliationError("Staged remote observation is not hash-valid") from exc
    return snapshot


def _source_check(journal: Path, snapshot: dict, task_id: str,
                  event_id: str) -> None:
    origin = snapshot["source_import"]
    if origin is None or origin.get("source_event_id") != event_id:
        raise ReconciliationError("Selected snapshot lacks the expected S2 import source")
    device_id, outbox = pilot.journal_state(journal)
    try:
        acknowledged_id, payload_hash = provenance.acknowledged_source(
            outbox, device_id, event_id
        )
    finally:
        outbox.close()
    if (acknowledged_id != task_id or origin["source_version"] != 1
            or origin["source_payload_sha256"] != payload_hash
            or not provenance.canonical_uuid(origin["receipt_id"])):
        raise ReconciliationError("S2 source and staged cloud receipt disagree")


def _local_view(canonical: Path, task_id: str) -> tuple[dict | None, list[str]]:
    with _read_only(canonical) as db:
        db.execute("PRAGMA query_only=ON")
        if db.execute("PRAGMA user_version").fetchone()[0] != 3:
            raise ReconciliationError("Canonical Rust task schema must be version 3")
        columns = set(row[1] for row in db.execute("PRAGMA table_info(tasks)"))
        if not set(RUST_COLUMNS).issubset(columns):
            raise ReconciliationError("Canonical Rust tasks do not match the expected schema")
        row = db.execute(
            "SELECT " + ",".join(RUST_COLUMNS) + " FROM tasks WHERE id=?",
            (task_id,),
        ).fetchone()
        edges = [
            entry[0] for entry in db.execute(
                "SELECT depends_on_id FROM task_dependencies "
                "WHERE task_id=? ORDER BY depends_on_id",
                (task_id,),
            )
        ] if row is not None else []
    local = dict(zip(RUST_COLUMNS, row)) if row is not None else None
    if local is not None and (type(local["version"]) is not int
                              or local["version"] < 1):
        raise ReconciliationError("Invalid canonical Rust task revision")
    if len(edges) != len(set(edges)):
        raise ReconciliationError("Duplicate local prerequisite identity")
    return local, edges


def reconcile(canonical: Path, shadow: Path, journal: Path,
              task_id: str, event_id: str) -> dict:
    """Produce a privacy-preserving report. Never perform an apply."""
    if not provenance.canonical_uuid(task_id):
        raise ReconciliationError("Select one canonical task UUID")
    canonical, shadow, journal = _distinct_paths([canonical, shadow, journal])
    snapshot = _preview_snapshot(shadow, task_id)
    _source_check(journal, snapshot, task_id, event_id)
    local, edges = _local_view(canonical, task_id)
    remote = snapshot["record"]
    changed_fields = [] if local is None else [
        key for key in COMMON_FIELDS if local[key] != remote[key]
    ]
    blockers = []
    if local is None:
        blockers.append("local-task-absent")
    elif local["deleted_at"] is not None:
        blockers.append("local-tombstone-present")
    if remote["deleted_at"] is not None:
        blockers.append("remote-tombstone-present")
    if edges != snapshot["depends_on"]:
        blockers.append("dependency-graph-disagreement")
    if local is not None and local["version"] > 1 and changed_fields:
        blockers.append("local-history-after-original-import")
    if remote["version"] > 1 and changed_fields:
        blockers.append("remote-history-after-original-import")
    if changed_fields:
        blockers.append("common-field-differences-require-review")
    blockers = sorted(set(blockers))
    return {
        "source_event_is_locally_acknowledged": True,
        "staged_s2_import_receipt_matches_local_source": True,
        "remote_snapshot_fingerprint_valid": True,
        "remote_snapshot_current_freshness_verified": False,
        "independent_owner_authenticated_receipt_recheck_needed": True,
        "canonical_local_task_found": local is not None,
        "canonical_local_revision": local["version"] if local is not None else None,
        "staged_remote_revision": remote["version"],
        "common_fields_different": len(changed_fields),
        "local_common_fields_unchanged": len(changed_fields) == 0 if local else None,
        "dependency_graph_equal": edges == snapshot["depends_on"],
        "rust_only_fields_present": bool(local and any(local[k] is not None for k in (
            "due_on", "estimate_minutes", "assignee_id", "completed_at",
        ))),
        "manual_review_blockers": blockers,
        "manual_review_required": True,
        "ready_for_apply": False,
        "safe_to_apply": False,
        "local_rust_sync": False,
        "network_called": False,
        "canonical_rust_database_modified": False,
        "cloudflare_database_modified": False,
        "content_written_to_new_file": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="S6 offline read-only original-source reconciliation"
    )
    parser.add_argument("--canonical", required=True, type=Path,
                        help="Existing private Rust tasks.sqlite3")
    parser.add_argument("--shadow", required=True, type=Path,
                        help="Existing private S4 *.pull-preview.sqlite3")
    parser.add_argument("--outbox", required=True, type=Path,
                        help="Existing private S2 tasks.sync.sqlite3")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--event-id", required=True)
    args = parser.parse_args()
    try:
        result = reconcile(args.canonical, args.shadow, args.outbox,
                           args.task_id, args.event_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except ReconciliationError as exc:
        print("SHIORI S6 review: " + str(exc), file=sys.stderr)
    except (pilot.SyncPilotError, provenance.ProvenanceError, review.ReviewError,
            sqlite3.Error, OSError, TypeError, ValueError):
        print("SHIORI S6 review: private input, receipt or database invalid; no writes",
              file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
