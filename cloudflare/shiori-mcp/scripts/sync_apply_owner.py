#!/usr/bin/env python3
"""S8 single-task, owner-approved live Cloudflare -> canonical Rust apply.

Zero background sync, zero remote writes. This orchestrator is the sole intended
caller of the hidden stdin-only Rust apply CLI. It proves an acknowledged local
S2 source, remotely attested receipt, exact staged AND freshly fetched S4
digest, unmodified local common fields, graph match, and explicit digest-bound
owner approval before Rust creates a private backup and performs local CAS.

The freshness guarantee is *at the authenticated read*, not a remote lock.
A concurrent remote edit after that read still requires next reconciliation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

import sync_import_pilot as pilot
import sync_local_reconcile as recon
import sync_provenance_check as provenance
import sync_pull_preview as pull
import sync_review as private

HEX64 = re.compile(r"^[0-9a-f]{64}$")
SOURCE_COMMON = ("title", "notes", "project", "priority", "status")


class ApplyError(ValueError):
    pass


def _original_source(outbox: Path, task_id: str, event_id: str) -> tuple[dict, str]:
    device, db = pilot.journal_state(outbox)
    try:
        original_id, payload_sha256 = provenance.acknowledged_source(
            db, device, event_id
        )
        if original_id != task_id:
            raise ApplyError("S2 original identity disagrees with selected task")
        row = db.execute("SELECT payload_json FROM sync_outbox WHERE event_id=?",
                         (event_id,)).fetchone()
        if row is None:
            raise ApplyError("Local original S2 source is missing")
        source = json.loads(row[0])["task"]
        if not isinstance(source, dict) or any(
            not isinstance(source.get(key), str) for key in SOURCE_COMMON
        ):
            raise ApplyError("Original source lacks required common task fields")
    finally:
        db.close()
    return source, payload_sha256


def _authenticated_current(token_file: Path, event_id: str, task_id: str,
                           local_source_hash: str, staged: dict) -> dict:
    token = pilot.read_token(token_file)
    receipt = pilot.api_call("sync.import.receipt.read", token,
                             {"event_id": event_id})
    provenance.attest_receipt(
        receipt, event_id, task_id, local_source_hash
    )
    live = pilot.api_call("sync.record.snapshot.read", token, {
        "task_id": task_id, "include_content": True,
    })
    try:
        pull.validate_snapshot(live, task_id)
    except pull.PullPreviewError as exc:
        raise ApplyError("Live owner-authenticated S4 snapshot is invalid") from exc
    if live["record_sha256"] != staged["record_sha256"]:
        raise ApplyError(
            "Cloud changed after selected S4 preview: capture and review a new snapshot"
        )
    origin = live["source_import"]
    if not origin or (
        origin["receipt_id"] != receipt["receipt_id"]
        or origin["source_event_id"] != event_id
        or origin["source_payload_sha256"] != local_source_hash
        or origin["source_version"] != 1
        or live["record"]["version"] != receipt["remote_revision"]
    ):
        raise ApplyError("Authenticated remote receipt no longer matches current S4 source")
    if live["record"]["deleted_at"] is not None:
        raise ApplyError("Cloud tombstone cannot be applied as a task resurrection")
    return live


def _preflight(canonical: Path, shadow: Path, outbox: Path, token_file: Path,
               task_id: str, event_id: str) -> tuple[dict, dict, int]:
    # Reject symlinks, world-readable files and hardlink/alias collisions
    # before any network call involving private task contents.
    canonical, shadow, outbox, token_file = recon._distinct_paths(
        [canonical, shadow, outbox, token_file]
    )
    if not provenance.canonical_uuid(task_id):
        raise ApplyError("Selected task ID must be a canonical UUID")
    report = recon.reconcile(canonical, shadow, outbox, task_id, event_id)
    source, sha256 = _original_source(outbox, task_id, event_id)
    local, edges = recon._local_view(canonical, task_id)
    staged = recon._preview_snapshot(shadow, task_id)
    if local is None or local["deleted_at"] is not None:
        raise ApplyError("Local task is missing or deleted")
    if staged["record"]["deleted_at"] is not None:
        raise ApplyError("Staged remote task is deleted")
    if edges != staged["depends_on"] or not report["dependency_graph_equal"]:
        raise ApplyError("Prerequisites disagree; require separate graph conflict review")
    # No last-write-wins: only an original S2-common-field state may take a
    # reviewed cloud projection. Local-only edits may have advanced revision;
    # Rust will retain due date, estimates, assignee, completion metadata.
    if any(local[key] != source[key] for key in SOURCE_COMMON):
        raise ApplyError(
            "Local common fields changed since original import; manual 3-way resolution required"
        )
    live = _authenticated_current(
        token_file, event_id, task_id, sha256, staged
    )
    if live["depends_on"] != edges:
        raise ApplyError("Live remote prerequisite graph differs from Rust")
    return local, live, len([
        key for key in SOURCE_COMMON if local[key] != live["record"][key]
    ])


def _backup_target(backup: Path, inputs: list[Path]) -> Path:
    if not backup.name.endswith(".shiori-backup.sqlite3"):
        raise ApplyError("Specify a new dedicated *.shiori-backup.sqlite3 destination")
    if backup.exists() or backup.is_symlink():
        raise ApplyError("Backup destination already exists; never overwrite it")
    parent = backup.parent.resolve(strict=True)
    if not parent.is_dir():
        raise ApplyError("Backup directory is not available")
    selected = parent / backup.name
    if selected in {p.resolve(strict=True) for p in inputs}:
        raise ApplyError("Backup destination aliases an existing sync input")
    return selected


def _local_apply(cli: Path, canonical: Path, backup: Path,
                 local_version: int, live: dict) -> int:
    task = live["record"]
    payload = {key: task[key] for key in (
        "id", "title", "notes", "project", "status", "priority"
    )}
    payload["depends_on"] = live["depends_on"]
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    if len(content) > 16_384:
        raise ApplyError("Reviewed task exceeds Rust stdin input budget")
    cmd = [str(cli), "--database", str(canonical),
           "sync-apply-reviewed", task["id"], "--if-version",
           str(local_version), "--backup-to", str(backup),
           "--confirm-reviewed-snapshot"]
    try:
        result = subprocess.run(cmd, input=content, capture_output=True,
                                timeout=40, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ApplyError(
            "Local apply outcome uncertain; inspect canonical revision and private backup"
        ) from exc
    if result.returncode != 0:
        raise ApplyError(
            "Rust rejected reviewed apply; task revision, prerequisites or backup may have changed"
        )
    returncode = result.returncode
    return returncode


def run(canonical: Path, shadow: Path, outbox: Path, token_file: Path,
        task_id: str, event_id: str, *, confirmed_content: bool,
        approved_digest: str | None = None, owner_approved: bool = False,
        backup: Path | None = None, cli: Path | None = None) -> dict:
    if not confirmed_content:
        raise ApplyError("Explicit --confirm-read-content is required")
    if owner_approved and (
        approved_digest is None or backup is None or cli is None
    ):
        raise ApplyError(
            "A local write requires --approve-digest, --backup-to, and --cli"
        )
    local, live, differences = _preflight(
        canonical, shadow, outbox, token_file, task_id, event_id
    )
    token_digest = live["record_sha256"]
    result = {
        "original_s2_source_and_owner_receipt_verified": True,
        "fresh_s4_matches_staged_observation": True,
        "remote_revision_at_read": live["record"]["version"],
        "local_revision_at_read": local["version"],
        "common_fields_to_review": differences,
        "dependency_graph_equal": True,
        "remote_observation_sha256_to_approve": token_digest,
        "owner_approval_present": owner_approved,
        "local_apply_committed": False,
        "automatic_sync": False,
        "cloudflare_mutated": False,
        "local_rust_sync": False,
    }
    if not owner_approved:
        # This first phase is useful by itself; the owner can independently
        # inspect the selected remote content, then approve its exact digest.
        return result
    if not isinstance(approved_digest, str) or not HEX64.fullmatch(approved_digest):
        raise ApplyError("Owner approval digest must be an exact SHA-256 observation")
    if approved_digest != token_digest:
        raise ApplyError("Owner approval refers to a different remote observation")
    if differences == 0:
        raise ApplyError("No reviewed common-field changes exist to apply")
    canonical, shadow, outbox, token_file = recon._distinct_paths(
        [canonical, shadow, outbox, token_file]
    )
    backup = _backup_target(backup, [canonical, shadow, outbox, token_file])
    if cli is None or not cli.is_file() or not cli.stat().st_mode & 0o111:
        raise ApplyError("Rust CLI executable is unavailable")
    _local_apply(cli, canonical, backup, local["version"], live)
    # Fail closed if the process committed but the resulting data disagrees.
    latest, current_edges = recon._local_view(canonical, task_id)
    if latest is None or current_edges != live["depends_on"] or any(
        latest[key] != live["record"][key] for key in SOURCE_COMMON
    ) or latest["version"] != local["version"] + 1:
        raise ApplyError(
            "Post-apply verification uncertain: retain backup and inspect before retrying"
        )
    result["local_apply_committed"] = True
    result["private_pre_apply_backup_created"] = True
    result["post_apply_local_revision"] = latest["version"]
    # It is still not continuous two-way sync or a remote revision map.
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Explicit one-task S8 source-verified cloud-to-Rust apply"
    )
    parser.add_argument("--canonical", type=Path, required=True)
    parser.add_argument("--shadow", type=Path, required=True)
    parser.add_argument("--outbox", type=Path, required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--confirm-read-content", action="store_true")
    parser.add_argument("--approve-digest")
    parser.add_argument("--confirm-apply", action="store_true")
    parser.add_argument("--backup-to", type=Path)
    parser.add_argument("--cli", type=Path)
    args = parser.parse_args()
    try:
        report = run(
            args.canonical, args.shadow, args.outbox, args.token_file,
            args.task_id, args.event_id,
            confirmed_content=args.confirm_read_content,
            approved_digest=args.approve_digest,
            owner_approved=args.confirm_apply, backup=args.backup_to,
            cli=args.cli,
        )
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    except (ApplyError, recon.ReconciliationError, pilot.SyncPilotError,
            provenance.ProvenanceError, pull.PullPreviewError,
            private.ReviewError, sqlite3.Error, OSError, ValueError):
        print(
            "SHIORI S8: source, freshness, conflict, consent or backup check failed; "
            "inspect private records and do not blindly retry", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
