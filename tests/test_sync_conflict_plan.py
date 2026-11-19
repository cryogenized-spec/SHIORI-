"""Two-device S5 CAS-planning acceptance; synthetic records, zero live writes."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare/shiori-mcp/scripts"))
import sync_conflict_plan as sync

A = "22222222-2222-4222-8222-222222222222"
B = "33333333-3333-4333-8333-333333333333"
TASK = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SOURCE = {"receipt_id": "88888888-8888-4888-8888-888888888888",
          "source_event_id": f"sync1:{A}:{TASK}:1",
          "source_version": 1, "source_payload_sha256": "e" * 64}


def snap(version=1, *, title="Owner task", notes="Base note", status="todo",
         deleted_at=None, dependencies=None, source=None, cutoff=None):
    record = {
        "id": TASK, "title": title, "notes": notes, "project": "Fixture",
        "status": status, "priority": "medium", "version": version,
        "created_at": "2026-11-18T20:00:00Z",
        "updated_at": "2026-11-18T20:00:00Z", "deleted_at": deleted_at,
    }
    src = SOURCE if source is None else source
    edges = [] if dependencies is None else dependencies
    sequence = version if cutoff is None else cutoff
    evidence = {"record": record, "depends_on": edges,
                "source_import": src, "cutoff": sequence}
    digest = hashlib.sha256(
        json.dumps(evidence, separators=(",", ":")).encode()
    ).hexdigest()
    return {**evidence, "record_sha256": digest,
            "consistent_snapshot": True, "local_rust_sync": False,
            "automatic_apply": False}


def reseal(snapshot):
    """Only test fixtures may deliberately recompute a modified observation."""
    evidence = {key: snapshot[key] for key in ("record", "depends_on", "source_import", "cutoff")}
    snapshot["record_sha256"] = hashlib.sha256(
        json.dumps(evidence, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return snapshot


def synthetic_cas(server, req):
    """One fixture-only conditional server edit; never accesses real task DB."""
    if server["record"]["version"] != req["expected_revision"]:
        raise sync.ConflictError("stale remote revision")
    if server["record_sha256"] != req["expected_record_sha256"]:
        raise sync.ConflictError("stale remote observation")
    if server["record"]["deleted_at"] is not None:
        raise sync.ConflictError("tombstone")
    if req["source_payload_sha256"] != SOURCE["source_payload_sha256"]:
        raise sync.ConflictError("origin")
    next_row = {**server["record"], **req["patch"]}
    next_row["version"] += 1
    next_observation = {
        "record": next_row, "depends_on": list(server["depends_on"]),
        "source_import": dict(server["source_import"]), "cutoff": server["cutoff"] + 1,
    }
    raw = json.dumps(next_observation, separators=(",", ":")).encode()
    return {**next_observation, "record_sha256": hashlib.sha256(raw).hexdigest(),
            "consistent_snapshot": True, "local_rust_sync": False,
            "automatic_apply": False}


class ConflictPlanningTests(unittest.TestCase):
    def test_two_devices_with_disjoint_edits_converge_via_version_pinned_cas(self):
        baseline = snap()
        device_a = sync.plan(baseline, baseline, {"status": "in_progress"})
        self.assertTrue(device_a["candidate_for_explicit_cas"])
        server_v2 = synthetic_cas(baseline, sync.approved_request(device_a, A, owner_approved=True))
        device_b = sync.plan(baseline, server_v2, {"notes": "Second offline note"})
        self.assertTrue(device_b["candidate_for_explicit_cas"])
        self.assertFalse(device_b["manual_conflict_resolution_required"])
        server_v3 = synthetic_cas(server_v2, sync.approved_request(device_b, B, owner_approved=True))
        self.assertEqual(server_v3["record"]["version"], 3)
        self.assertEqual(server_v3["record"]["status"], "in_progress")
        self.assertEqual(server_v3["record"]["notes"], "Second offline note")
        # One owner-requested refreshed snapshot gives both devices equal data.
        device_a_after_pull, device_b_after_pull = copy.deepcopy(server_v3), copy.deepcopy(server_v3)
        self.assertEqual(device_a_after_pull["record"], device_b_after_pull["record"])
        self.assertEqual(device_a_after_pull["record_sha256"], device_b_after_pull["record_sha256"])

    def test_overlapping_stale_field_never_auto_merges(self):
        base, remote = snap(), snap(2, notes="Remote note")
        result = sync.plan(base, remote, {"notes": "Different offline note"})
        self.assertEqual(result["conflict_kinds"], ["overlapping-field-edit"])
        self.assertFalse(result["candidate_for_explicit_cas"])
        with self.assertRaisesRegex(sync.ConflictError, "Conflicts"):
            sync.approved_request(result, B, owner_approved=True)

    def test_same_value_changed_concurrently_is_already_converged(self):
        result = sync.plan(snap(), snap(2, notes="Agreed note"), {"notes": "Agreed note"})
        self.assertEqual(result["already_converged_fields"], 1)
        self.assertFalse(result["candidate_for_explicit_cas"])

    def test_delete_vs_offline_edit_blocks_resurrection(self):
        base = snap()
        remote = snap(2, deleted_at="2026-11-18T20:05:00Z")
        result = sync.plan(base, remote, {"title": "Offline edit"})
        self.assertIn("delete-resurrection-risk", result["conflict_kinds"])
        self.assertFalse(result["candidate_for_explicit_cas"])

    def test_dependency_edit_requires_separate_graph_review(self):
        remote = snap(2, dependencies=["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"])
        result = sync.plan(snap(), remote, {"notes": "Offline notes"})
        self.assertIn("dependency-graph-changed", result["conflict_kinds"])

    def test_wrong_source_receipt_and_revision_regressions_refused(self):
        bad = snap(2)
        bad["source_import"] = {**SOURCE, "source_payload_sha256": "f"*64}
        reseal(bad)
        with self.assertRaisesRegex(sync.ConflictError, "lineage"):
            sync.plan(snap(), bad, {"status": "done"})
        with self.assertRaisesRegex(sync.ConflictError, "regressed"):
            sync.plan(snap(3), snap(2), {"status": "done"})

    def test_requires_explicit_approval_and_paired_uuid(self):
        item = sync.plan(snap(), snap(), {"status": "done"})
        with self.assertRaisesRegex(sync.ConflictError, "approve"):
            sync.approved_request(item, A, owner_approved=False)
        with self.assertRaisesRegex(sync.ConflictError, "UUID"):
            sync.approved_request(item, "unpaired", owner_approved=True)
        req = sync.approved_request(item, A, owner_approved=True)
        self.assertEqual(req["owner_approved"], True)
        self.assertEqual(req["expected_revision"], 1)
        self.assertEqual(req["source_event_id"], SOURCE["source_event_id"])
        self.assertEqual(len(req["expected_record_sha256"]), 64)
        self.assertTrue(req["idempotency_key"].startswith("s5-"))

    def test_repeated_owner_approval_generates_same_idempotency_key(self):
        planned = sync.plan(snap(), snap(), {"notes": "Sensitive private note"})
        req1 = sync.approved_request(planned, A, owner_approved=True)
        req2 = sync.approved_request(planned, A, owner_approved=True)
        self.assertEqual(req1["idempotency_key"], req2["idempotency_key"])
        self.assertNotIn("Sensitive private note", req1["idempotency_key"])

    def test_stale_server_snapshot_fails_compare_and_swap(self):
        base = snap()
        planned = sync.plan(base, base, {"status": "in_progress"})
        req = sync.approved_request(planned, A, owner_approved=True)
        with self.assertRaisesRegex(sync.ConflictError, "stale remote"):
            synthetic_cas(snap(2, notes="Concurrent edit"), req)
        self.assertEqual(base["record"]["version"], 1)

    def test_no_implicit_write_for_invalid_or_unsupported_fields(self):
        for fields in ({"due_on": "2026-11-30"}, {"title": ""}, {"status": "unknown"},
                       {"notes": "x" * 9000}, {"title": "Changed", "id": TASK}, {}):
            with self.subTest(fields=tuple(fields)):
                with self.assertRaises(sync.ConflictError):
                    sync.plan(snap(), snap(), fields)

    def test_tampered_record_with_unchanged_digest_is_rejected(self):
        base = snap()
        remote = copy.deepcopy(base)
        remote["record"]["notes"] = "Tampered remote note"
        with self.assertRaisesRegex(sync.ConflictError, "digest"):
            sync.plan(base, remote, {"status": "done"})

    def test_tampered_dependencies_and_source_are_rejected(self):
        for field, value in (
            ("depends_on", ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"]),
            ("source_import", {**SOURCE, "source_payload_sha256": "f" * 64}),
        ):
            with self.subTest(field=field):
                remote = snap()
                remote[field] = value
                with self.assertRaisesRegex(sync.ConflictError, "digest"):
                    sync.plan(snap(), remote, {"status": "done"})

    def test_malformed_digest_and_unexpected_fields_fail_closed(self):
        for mutation in ("invalid-digest", "extra-field"):
            with self.subTest(mutation=mutation):
                remote = snap()
                if mutation == "invalid-digest":
                    remote["record_sha256"] = "g" * 64
                else:
                    remote["unexpected"] = "unsafe"
                with self.assertRaises(sync.ConflictError):
                    sync.plan(snap(), remote, {"status": "done"})

    def test_distinct_snapshot_identity_refused(self):
        data = snap()
        other = snap()
        other["record"]["id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
        reseal(other)
        with self.assertRaisesRegex(sync.ConflictError, "identity"):
            sync.plan(data, other, {"status": "done"})


if __name__ == "__main__":
    unittest.main()
