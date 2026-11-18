#!/usr/bin/env python3
"""Deterministic S5 owner-reviewed 3-way conflict plan for SHIORI common task fields.

Pure logic; no IO, Cloudflare requests or canonical task writes. A planned
request is not an authorization: server must independently verify version,
content hash, paired device status, original S2 receipt and owner approval.
"""
from __future__ import annotations

import hashlib
import json
from uuid import UUID

FIELDS = {"title", "notes", "project", "status", "priority"}
STATUSES = {"todo", "in_progress", "done"}
PRIORITIES = {"low", "medium", "high", "urgent"}


class ConflictError(ValueError):
    pass


def valid_uuid(raw: object) -> bool:
    if not isinstance(raw, str) or len(raw) != 36:
        return False
    try:
        return str(UUID(raw)) == raw
    except ValueError:
        return False


def _schema(snapshot: object, name: str) -> dict:
    if (not isinstance(snapshot, dict)
            or snapshot.get("consistent_snapshot") is not True
            or snapshot.get("automatic_apply") is not False
            or snapshot.get("local_rust_sync") is not False
            or not isinstance(snapshot.get("record"), dict)
            or not isinstance(snapshot.get("record_sha256"), str)
            or len(snapshot["record_sha256"]) != 64
            or not isinstance(snapshot.get("depends_on"), list)
            or type(snapshot.get("cutoff")) is not int):
        raise ConflictError(f"{name} has invalid or unverified snapshot metadata")
    record = snapshot["record"]
    if (not valid_uuid(record.get("id"))
            or type(record.get("version")) is not int
            or record["version"] < 1
            or any(field not in record for field in FIELDS | {"deleted_at"})):
        raise ConflictError(f"{name} has invalid task identity or revision")
    return record


def plan(base: dict, remote: dict, local_fields: dict) -> dict:
    """Compare one device's deliberate offline edits with a fresh D1 snapshot.

    local_fields is ONLY the intended changed common-field subset; it never
    silently fills omitted Rust-only due dates, estimates or assignments.
    """
    old = _schema(base, "base")
    current = _schema(remote, "remote")
    if old["id"] != current["id"]:
        raise ConflictError("Local origin and current remote task identity differ")
    if (current["version"] < old["version"]
            or remote["cutoff"] < base["cutoff"]
            or base.get("source_import") is None
            or base.get("source_import") != remote.get("source_import")):
        raise ConflictError("Source lineage changed or remote revision regressed")
    if not isinstance(local_fields, dict) or not local_fields or not set(local_fields) <= FIELDS:
        raise ConflictError("Choose one or more supported common task fields")
    for field, value in local_fields.items():
        if not isinstance(value, str):
            raise ConflictError("Changed task field must be text")
        if field == "title" and not 1 <= len(value.strip()) <= 160:
            raise ConflictError("Invalid edited title")
        if field == "notes" and len(value) > 8192:
            raise ConflictError("Edited notes exceed 8 KiB")
        if field == "project" and not 1 <= len(value.strip()) <= 160:
            raise ConflictError("Invalid edited project")
        if field == "status" and value not in STATUSES:
            raise ConflictError("Invalid edited status")
        if field == "priority" and value not in PRIORITIES:
            raise ConflictError("Invalid edited priority")
    blockers = []
    changed = {}
    already_converged = []
    for field, value in local_fields.items():
        previous = old[field]
        server = current[field]
        if value == previous:
            continue
        if server == value:
            already_converged.append(field)
            continue
        if server != previous:
            blockers.append("overlapping-field-edit")
            continue
        changed[field] = value
    if old["deleted_at"] is not None or current["deleted_at"] is not None:
        blockers.append("delete-resurrection-risk")
    if base["depends_on"] != remote["depends_on"]:
        blockers.append("dependency-graph-changed")
    blockers = sorted(set(blockers))
    return {
        # Private patch remains available to the controlled caller, not CLI output.
        "patch": changed if not blockers else {},
        "owner_review_needed": True,
        "conflict_kinds": blockers,
        "already_converged_fields": len(already_converged),
        "proposed_changed_fields": len(changed) if not blockers else 0,
        "expected_remote_revision": current["version"],
        "expected_record_sha256": remote["record_sha256"],
        "source_event_id": remote["source_import"]["source_event_id"],
        "source_payload_sha256": remote["source_import"]["source_payload_sha256"],
        "remote_task_id": current["id"],
        "manual_conflict_resolution_required": bool(blockers),
        "candidate_for_explicit_cas": bool(changed) and not blockers,
        "remote_write_performed": False,
        "canonical_rust_write_performed": False,
        "safe_to_apply": False,
    }


def approved_request(result: dict, device_id: str, *, owner_approved: bool) -> dict:
    """Construct but NEVER send a bounded version/hash pinned write proposal."""
    if not owner_approved:
        raise ConflictError("Owner must explicitly review and approve the proposed changed fields")
    if not valid_uuid(device_id):
        raise ConflictError("Paired device ID must be a canonical UUID")
    if (not result.get("candidate_for_explicit_cas")
            or result.get("manual_conflict_resolution_required")
            or not result.get("patch")):
        raise ConflictError("Conflicts or no-op plan cannot become a write request")
    patch = result["patch"]
    canonical = json.dumps({
        "device": device_id, "task": result["remote_task_id"],
        "expected_revision": result["expected_remote_revision"],
        "expected_digest": result["expected_record_sha256"],
        "patch": dict(sorted(patch.items())),
    }, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    key = "s5-" + hashlib.sha256(canonical).hexdigest()
    return {
        "workspace_id": "personal",
        "device_id": device_id,
        "task_id": result["remote_task_id"],
        "source_event_id": result["source_event_id"],
        "source_payload_sha256": result["source_payload_sha256"],
        "expected_revision": result["expected_remote_revision"],
        "expected_record_sha256": result["expected_record_sha256"],
        "patch": patch,
        "owner_approved": True,
        "idempotency_key": key,
    }
