#!/usr/bin/env python3
"""Read-only, receipt-aware SHIORI S3 local/remote metadata review.

An approved S2 receipt can attest historical *source identity* for ONE task
whose ID is visible on both sides. It cannot establish current task content,
lineage after a purge/reinsert, or authorization to apply remote changes.
All output is aggregate-only. No task data, text or payload is transferred.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

import sync_import_pilot as pilot
import sync_provenance_check as provenance
import sync_review as baseline


class LinkedReviewError(ValueError):
    pass


def classify(local: dict, remote: dict, impact: dict, task_id: str,
             attestation: dict, aggregate: dict) -> dict:
    """Mark a historically witnessed S2 overlap without trusting current state."""
    if task_id not in local or task_id not in remote:
        raise LinkedReviewError(
            "Acknowledged first-import identity must exist in both staged inventories"
        )
    if not attestation.get("s2_source_provenance_confirmed", False):
        raise LinkedReviewError("Authenticated S2 import provenance not established")
    shared = len(set(local).intersection(remote))
    local_version, _, local_deleted_at = local[task_id]
    baseline_version, _, baseline_deleted_at = remote[task_id]
    observed_remote_version = attestation["remote_observed_revision"]
    changed = impact["changed_task_ids"]
    deps = impact["edge_endpoints"]
    deletes = impact["delete_ids"]
    if not all(type(v) is int and v >= 1 for v in
               (local_version, baseline_version, observed_remote_version)):
        raise LinkedReviewError("Invalid revision in receipt-aware review")
    return {
        **aggregate,
        "authenticated_historical_s2_receipt_count": 1,
        "historically_attested_shared_task_ids": 1,
        "shared_task_ids_without_authenticated_s2_receipt": shared - 1,
        # This remains unverified even with a historical receipt: D1 could
        # have been modified, purged or recreated, and metadata has no body.
        "current_record_provenance_verified": False,
        "current_task_content_equivalence_verified": False,
        "attested_task_local_revision": local_version,
        "attested_task_staged_baseline_revision": baseline_version,
        "attested_task_receipt_observed_remote_revision": observed_remote_version,
        "attested_task_local_changed_since_original_import":
            local_version != 1 or local_deleted_at is not None,
        "attested_task_remote_changed_since_original_import":
            bool(attestation["remote_modified_since_import"]) or
            baseline_version != 1 or baseline_deleted_at is not None,
        "attested_task_local_vs_staged_remote_revision_disagreement":
            local_version != baseline_version,
        "attested_task_local_vs_staged_remote_deleted_disagreement":
            bool(local_deleted_at) != bool(baseline_deleted_at),
        "attested_task_has_post_baseline_remote_task_events": task_id in changed,
        "attested_task_has_post_baseline_remote_dependency_events": task_id in deps,
        "attested_task_has_post_baseline_delete_or_purge_event": task_id in deletes,
        "manual_identity_and_conflict_review_required": True,
        "safe_to_apply": False,
        "local_rust_sync": False,
        "task_content_transferred": False,
        "local_or_remote_task_writes": False,
    }


def verify_review(local_manifest: Path, pull_journal: Path, outbox: Path,
                  token_file: Path, event_id: str) -> dict:
    """Verify private inputs offline before making ONE owner-authenticated read."""
    local, local_edges = baseline.local_manifest(
        baseline.private_file_bytes(local_manifest, baseline.MAX_LOCAL_BYTES)
    )
    remote, remote_edges, cutoff, checkpoint, delta, incomplete, impact = (
        baseline.baseline_journal(pull_journal, include_delta=True)
    )
    device_id, db = pilot.journal_state(outbox)
    try:
        task_id, digest = provenance.acknowledged_source(db, device_id, event_id)
    finally:
        db.close()
    # Reject missing overlap *before* contacting Cloudflare: no remote probing
    # of arbitrary event IDs from an unrecognized local or baseline identity.
    if task_id not in local or task_id not in remote:
        raise LinkedReviewError(
            "Acknowledged first-import identity must exist in both staged inventories"
        )
    token = pilot.read_token(token_file)
    receipt = pilot.api_call(
        "sync.import.receipt.read", token, {"event_id": event_id}
    )
    attestation = provenance.attest_receipt(receipt, event_id, task_id, digest)
    aggregate = baseline.compare(
        local, local_edges, remote, remote_edges, cutoff, checkpoint,
        delta, incomplete, impact
    )
    return classify(local, remote, impact, task_id, attestation, aggregate)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only S3 historical source-overlap + conflict-risk counts"
    )
    parser.add_argument("--local-manifest", type=Path, required=True,
                        help="Private binary shiori-cli bridge-manifest export")
    parser.add_argument("--pull-journal", type=Path, required=True,
                        help="Private staged S3 v2 pull journal (read-only)")
    parser.add_argument("--outbox", type=Path, required=True,
                        help="Private S1/S2 Rust outbox (read-only)")
    parser.add_argument("--token-file", type=Path, required=True,
                        help="Private owner bearer file, NOT OAuth approval code")
    parser.add_argument("--event-id", required=True,
                        help="One acknowledged S2 sync1:... event")
    args = parser.parse_args()
    try:
        result = verify_review(
            args.local_manifest, args.pull_journal, args.outbox,
            args.token_file, args.event_id,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (LinkedReviewError, baseline.ReviewError,
            provenance.ProvenanceError, pilot.SyncPilotError,
            sqlite3.Error, OSError, ValueError) as exc:
        print("SHIORI receipt-aware review: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
