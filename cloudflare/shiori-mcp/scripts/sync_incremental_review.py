#!/usr/bin/env python3
"""S10: read-only, owner-authenticated checkpoint-based divergence classifier.

This makes the S9 witness useful for NEXT sync cycle: classify local-only,
cloud-only, shared-content, metadata and dual-edited states without last-write-
wins or any canonical/remote task writes. Never trusts a saved cloud snapshot
as current; owner-authenticated S2 receipt and S4 live record are mandatory.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys

import sync_apply_owner as owner
import sync_import_pilot as pilot
import sync_local_reconcile as reconcile
import sync_provenance_check as provenance
import sync_pull_preview as preview
import sync_revision_checkpoint as checkpoint

CHECKPOINT_COLUMNS = (
    "event_id", "source_payload_sha256", "remote_record_sha256",
    "remote_version", "local_version", "local_common_sha256",
    "remote_change_cutoff",
)


class DivergenceError(ValueError):
    """No title, notes, task ID, token or other private values in messages."""


def _stored_checkpoint(path: Path, task_id: str) -> dict:
    if not path.name.endswith(".sync-checkpoint.sqlite3"):
        raise DivergenceError("Expected a dedicated S9 private checkpoint file")
    with closing(reconcile._read_only(path)) as db:
        db.execute("PRAGMA query_only=ON")
        version = db.execute("PRAGMA user_version").fetchone()
        kind = db.execute(
            "SELECT value FROM checkpoint_meta WHERE key='kind'"
        ).fetchone()
        if version != (1,) or kind != (checkpoint.MAGIC,):
            raise DivergenceError("Unrecognized S9 checkpoint database")
        row = db.execute(
            "SELECT " + ",".join(CHECKPOINT_COLUMNS) +
            " FROM checkpoints WHERE task_id=?", (task_id,)
        ).fetchone()
    if row is None:
        raise DivergenceError("No previously approved S9 checkpoint exists for this task")
    data = dict(zip(CHECKPOINT_COLUMNS, row))
    if (not provenance.canonical_uuid(task_id)
            or type(data["local_version"]) is not int or data["local_version"] < 1
            or type(data["remote_version"]) is not int or data["remote_version"] < 1
            or type(data["remote_change_cutoff"]) is not int
            or data["remote_change_cutoff"] < 0
            or any(not isinstance(data[key], str) or len(data[key]) != 64
                   or any(char not in "0123456789abcdef" for char in data[key])
                   for key in ("source_payload_sha256", "remote_record_sha256",
                               "local_common_sha256"))):
        raise DivergenceError("Stored checkpoint revisions or fingerprints are invalid")
    return data


def review(canonical: Path, shadow: Path, journal: Path, token_file: Path,
           checkpoint_file: Path, task_id: str, event_id: str,
           *, confirmed_content: bool) -> dict:
    if not confirmed_content:
        raise DivergenceError("Owner must explicitly confirm the content-bearing S4 read")
    if not provenance.canonical_uuid(task_id):
        raise DivergenceError("Select a canonical task UUID")
    paths = reconcile._distinct_paths([
        canonical, shadow, journal, token_file, checkpoint_file,
    ])
    canonical, shadow, journal, token_file, checkpoint_file = paths
    base = _stored_checkpoint(checkpoint_file, task_id)
    if base["event_id"] != event_id:
        raise DivergenceError("Checkpoint is for a different original S2 source")
    staged = reconcile._preview_snapshot(shadow, task_id)
    reconcile._source_check(journal, staged, task_id, event_id)
    _, source_sha256 = owner._original_source(journal, task_id, event_id)
    if (base["source_payload_sha256"] != source_sha256
            or base["remote_record_sha256"] != staged["record_sha256"]
            or base["remote_version"] != staged["record"]["version"]
            or base["remote_change_cutoff"] != staged["cutoff"]
            or base["local_common_sha256"] != checkpoint._common_hash(staged["record"])):
        raise DivergenceError("S9 witness and original approved snapshot do not match")
    local, edges = reconcile._local_view(canonical, task_id)
    if local is None:
        raise DivergenceError("Canonical local task missing; never infer a safe insert")
    if local["version"] < base["local_version"]:
        raise DivergenceError("Canonical Rust revision regressed since approved checkpoint")
    token = pilot.read_token(token_file)
    receipt = pilot.api_call(
        "sync.import.receipt.read", token, {"event_id": event_id}
    )
    provenance.attest_receipt(receipt, event_id, task_id, source_sha256)
    live = pilot.api_call("sync.record.snapshot.read", token, {
        "task_id": task_id, "include_content": True,
    })
    try:
        preview.validate_snapshot(live, task_id)
    except preview.PullPreviewError as exc:
        raise DivergenceError("Fresh S4 observation failed content verification") from exc
    origin = live["source_import"]
    if not origin or (
        origin["receipt_id"] != receipt["receipt_id"]
        or origin["source_event_id"] != event_id
        or origin["source_payload_sha256"] != source_sha256
        or origin["source_version"] != 1
        or live["record"]["version"] != receipt["remote_revision"]
    ):
        raise DivergenceError("Fresh S4 record has different original source provenance")
    if live["record"]["version"] < base["remote_version"]:
        raise DivergenceError("Cloud revision regressed after the approved checkpoint")
    if live["cutoff"] < base["remote_change_cutoff"]:
        raise DivergenceError("Cloud change-feed cutoff regressed after the checkpoint")
    local_changed = checkpoint._common_hash(local) != base["local_common_sha256"]
    remote_changed = checkpoint._common_hash(live["record"]) != base["local_common_sha256"]
    local_graph_changed = edges != staged["depends_on"]
    remote_graph_changed = live["depends_on"] != staged["depends_on"]
    tombstone = local["deleted_at"] is not None or live["record"]["deleted_at"] is not None
    revision_suspicious = (
        (local_changed and local["version"] == base["local_version"])
        or (live["record"]["version"] == base["remote_version"]
            and live["record"] != staged["record"])
    )
    if tombstone:
        status = "delete_conflict"
    elif local_graph_changed or remote_graph_changed:
        status = "dependency_conflict"
    elif revision_suspicious:
        status = "unversioned_mutation_conflict"
    elif local_changed and remote_changed:
        status = "two_sided_content_conflict"
    elif local_changed:
        status = "local_only_change_for_owner_review"
    elif remote_changed:
        status = "remote_only_change_for_owner_review"
    elif (local["version"] != base["local_version"]
          or live["record"]["version"] != base["remote_version"]):
        status = "revision_without_common_content_change"
    else:
        status = "aligned_at_current_owner_read"
    # A changed global D1 cutoff by itself can be an unrelated task event,
    # and must not masquerade as a changed version of this specific record.
    only_global_cutoff_advanced = (
        status == "aligned_at_current_owner_read"
        and live["record"] == staged["record"]
        and live["depends_on"] == staged["depends_on"]
        and live["source_import"] == staged["source_import"]
        and live["cutoff"] > staged["cutoff"]
    )
    return {
        "status": status,
        "checkpoint_local_revision": base["local_version"],
        "current_local_revision": local["version"],
        "checkpoint_remote_revision": base["remote_version"],
        "current_remote_revision": live["record"]["version"],
        "local_common_fields_changed": local_changed,
        "remote_common_fields_changed": remote_changed,
        "local_dependency_graph_changed": local_graph_changed,
        "remote_dependency_graph_changed": remote_graph_changed,
        "local_or_remote_tombstone": tombstone,
        "only_global_changefeed_cutoff_advanced": only_global_cutoff_advanced,
        "original_s2_source_reauthenticated": True,
        "fresh_remote_content_verified": True,
        "conflict_requires_manual_resolution": status in (
            "delete_conflict", "dependency_conflict",
            "unversioned_mutation_conflict", "two_sided_content_conflict",
        ),
        "owner_review_required_before_any_apply": True,
        "safe_to_apply": False,
        "automatic_sync": False,
        "local_rust_database_modified": False,
        "cloudflare_database_modified": False,
        "checkpoint_modified": False,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Owner-controlled read-only S10 incremental divergence review"
    )
    for field in ("canonical", "shadow", "journal", "token_file", "checkpoint_file"):
        ap.add_argument("--" + field.replace("_", "-"), type=Path, required=True)
    ap.add_argument("--task-id", required=True)
    ap.add_argument("--event-id", required=True)
    ap.add_argument("--confirm-read-content", action="store_true")
    a = ap.parse_args()
    try:
        result = review(
            a.canonical, a.shadow, a.journal, a.token_file,
            a.checkpoint_file, a.task_id, a.event_id,
            confirmed_content=a.confirm_read_content,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (DivergenceError, checkpoint.CheckpointError,
            reconcile.ReconciliationError, provenance.ProvenanceError,
            pilot.SyncPilotError, preview.PullPreviewError,
            sqlite3.Error, OSError, ValueError, TypeError):
        print(
            "SHIORI S10: source, checkpoint, content or local revision check failed; "
            "no task/remote/checkpoint writes", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
