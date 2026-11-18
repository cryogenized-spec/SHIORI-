"""Synthetic receipt-aware S3 review; never opens or writes canonical tasks."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare/shiori-mcp/scripts"))
import sync_receipt_review as review
import sync_review as baseline
import sync_import_pilot as pilot
import sync_provenance_check as provenance

DEVICE = "22222222-2222-4222-8222-222222222222"
TASK = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SECOND = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
THIRD = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
RECEIPT = "88888888-8888-4888-8888-888888888888"
EVENT = f"sync1:{DEVICE}:{TASK}:1"
PRIVATE_NOTE = "DO NOT COPY CUSTOMER NOTE"


def private(path, content):
    path.write_bytes(content)
    os.chmod(path, 0o600)


class ReceiptReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest_path = self.root / "bridge.manifest"
        self.pull_path = self.root / "tasks.pull.sqlite3"
        self.outbox_path = self.root / "tasks.sync.sqlite3"
        self.token_path = self.root / "owner.token"
        self.canonical_path = self.root / "tasks.sqlite3"
        self.canonical_path.write_bytes(b"ORIGINAL CANONICAL TASKS - MUST REMAIN UNTOUCHED")
        self.token_path.write_text("SYNTHETIC_BEARER_TOKEN", encoding="utf8")
        os.chmod(self.token_path, 0o600)
        self.envelope = json.dumps({
            "schema_version": 1, "event_id": EVENT, "origin_device_id": DEVICE,
            "workspace_id": "personal", "depends_on": [],
            "task": {"id": TASK, "version": 1, "deleted_at": None,
                     "title": "PRIVATE TASK", "notes": PRIVATE_NOTE}
        }, separators=(",", ":"))
        self.digest = hashlib.sha256(self.envelope.encode()).hexdigest()
        self.make_manifest()
        self.make_pull()
        self.make_outbox()

    def make_manifest(self, local_version=1, deleted=None, include_first=True):
        data = bytearray(baseline.MARKER)
        items = []
        if include_first:
            items.append((TASK, str(local_version), "todo", "2026-11-18T09:00:00Z",
                          deleted or "", ""))
        items.append((THIRD, "1", "todo", "2026-11-18T09:00:00Z", "", ""))
        for row in sorted(items):
            for field in row:
                raw = field.encode()
                data.extend(struct.pack(">I", len(raw)))
                data.extend(raw)
        private(self.manifest_path, bytes(data))

    def make_pull(self, include_first=True, version=1, deleted=None):
        sample = {
            "items": [
                {"id": task, "version": version if task == TASK else 1,
                 "status": "todo", "updated_at": "2026-11-18T09:00:00Z",
                 "deleted_at": deleted if task == TASK else None}
                for task in ([TASK, SECOND] if include_first else [SECOND])
            ],
            "edges": [],
            "cutoff": 7, "task_count": 2 if include_first else 1,
            "edge_count": 0,
            "consistent_snapshot": True, "local_rust_sync": False,
            "automatic_apply": False,
        }
        digest = hashlib.sha256(
            json.dumps(sample, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        if self.pull_path.exists():
            self.pull_path.unlink()
        db = sqlite3.connect(self.pull_path)
        db.executescript("""
            CREATE TABLE pull_state(
              workspace_id TEXT PRIMARY KEY, cursor INTEGER, cutoff INTEGER,
              baseline_required INTEGER
            );
            CREATE TABLE pull_events(
              seq INTEGER PRIMARY KEY, kind TEXT, task_id TEXT,
              depends_on_id TEXT, task_version INTEGER, occurred_at TEXT
            );
            CREATE TABLE pull_baseline_meta(
              workspace_id TEXT PRIMARY KEY, cutoff INTEGER,
              task_count INTEGER, edge_count INTEGER, sha256 TEXT
            );
            CREATE TABLE pull_baseline_tasks(
              id TEXT PRIMARY KEY, version INTEGER, status TEXT,
              updated_at TEXT, deleted_at TEXT
            );
            CREATE TABLE pull_baseline_edges(
              task_id TEXT, depends_on_id TEXT,
              PRIMARY KEY(task_id,depends_on_id)
            );
            PRAGMA user_version=2;
        """)
        db.execute("INSERT INTO pull_state VALUES('personal',7,NULL,1)")
        db.execute("INSERT INTO pull_baseline_meta VALUES(?,?,?,?,?)",
                   ("personal", 7, sample["task_count"], 0, digest))
        db.executemany("INSERT INTO pull_baseline_tasks VALUES(?,?,?,?,?)",
                       [(x["id"], x["version"], x["status"], x["updated_at"],
                         x["deleted_at"]) for x in sample["items"]])
        db.commit()
        db.close()
        os.chmod(self.pull_path, 0o600)

    def make_outbox(self, state="acknowledged"):
        db = sqlite3.connect(self.outbox_path)
        db.executescript("""
            CREATE TABLE sync_meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE sync_outbox(
              event_id TEXT PRIMARY KEY, task_id TEXT, local_version INTEGER,
              payload_json TEXT, state TEXT, remote_id TEXT,
              remote_version INTEGER
            );
            PRAGMA user_version=1;
        """)
        db.execute("INSERT INTO sync_meta VALUES('device_id',?)", (DEVICE,))
        db.execute("INSERT INTO sync_outbox VALUES(?,?,?,?,?,?,?)",
                   (EVENT, TASK, 1, self.envelope, state, TASK, 1))
        db.commit()
        db.close()
        os.chmod(self.outbox_path, 0o600)

    def receipt(self, version=1):
        return {
            "receipt_id": RECEIPT, "resource_id": TASK,
            "source_event_id": EVENT, "source_version": 1,
            "remote_revision": version, "source_payload_sha256": self.digest,
            "remote_modified": version != 1,
        }

    def inspect(self):
        return review.verify_review(self.manifest_path, self.pull_path,
                                    self.outbox_path, self.token_path, EVENT)

    def test_one_historical_receipt_reduces_unattested_overlap_but_not_apply_guard(self):
        with patch.object(pilot, "api_call", return_value=self.receipt()) as api:
            result = self.inspect()
        api.assert_called_once_with(
            "sync.import.receipt.read", "SYNTHETIC_BEARER_TOKEN",
            {"event_id": EVENT}
        )
        self.assertEqual(result["historically_attested_shared_task_ids"], 1)
        self.assertEqual(result["shared_task_ids_without_authenticated_s2_receipt"], 0)
        self.assertEqual(result["local_only_ids"], 1)
        self.assertEqual(result["remote_only_baseline_ids"], 1)
        self.assertTrue(result["manual_identity_and_conflict_review_required"])
        self.assertFalse(result["current_record_provenance_verified"])
        self.assertFalse(result["current_task_content_equivalence_verified"])
        self.assertFalse(result["safe_to_apply"])
        self.assertFalse(result["task_content_transferred"])
        self.assertFalse(result["local_or_remote_task_writes"])
        output = json.dumps(result)
        for secret in (TASK, SECOND, THIRD, DEVICE, EVENT, PRIVATE_NOTE, self.digest):
            self.assertNotIn(secret, output)
        self.assertEqual(self.canonical_path.read_bytes(),
                         b"ORIGINAL CANONICAL TASKS - MUST REMAIN UNTOUCHED")

    def test_post_baseline_events_flag_changed_task_and_dependency(self):
        with sqlite3.connect(self.pull_path) as db:
            db.execute("INSERT INTO pull_events VALUES(8,'task.update',?,NULL,2,?)",
                       (TASK, "2026-11-18T11:00:00Z"))
            db.execute("INSERT INTO pull_events VALUES(9,'edge.add',?,?,NULL,?)",
                       (TASK, SECOND, "2026-11-18T11:01:00Z"))
            db.execute("UPDATE pull_state SET cursor=9")
        with patch.object(pilot, "api_call", return_value=self.receipt(2)):
            result = self.inspect()
        self.assertTrue(result["attested_task_has_post_baseline_remote_task_events"])
        self.assertTrue(result["attested_task_has_post_baseline_remote_dependency_events"])
        self.assertTrue(result["attested_task_remote_changed_since_original_import"])
        self.assertFalse(result["current_record_provenance_verified"])
        self.assertFalse(result["safe_to_apply"])

    def test_post_baseline_delete_is_not_automatically_applied(self):
        with sqlite3.connect(self.pull_path) as db:
            db.execute("INSERT INTO pull_events VALUES(8,'task.delete',?,NULL,2,?)",
                       (TASK, "2026-11-18T11:00:00Z"))
            db.execute("UPDATE pull_state SET cursor=8")
        with patch.object(pilot, "api_call", return_value=self.receipt(2)):
            out = self.inspect()
        self.assertTrue(out["attested_task_has_post_baseline_delete_or_purge_event"])
        self.assertFalse(out["safe_to_apply"])
        self.assertTrue(out["manual_identity_and_conflict_review_required"])

    def test_local_edits_and_tombstones_are_reported_without_writes(self):
        self.make_manifest(local_version=3, deleted="2026-11-18T11:00:00Z")
        with patch.object(pilot, "api_call", return_value=self.receipt()):
            result = self.inspect()
        self.assertTrue(result["attested_task_local_changed_since_original_import"])
        self.assertTrue(result["attested_task_local_vs_staged_remote_revision_disagreement"])
        self.assertTrue(result["attested_task_local_vs_staged_remote_deleted_disagreement"])
        self.assertFalse(result["safe_to_apply"])

    def test_local_missing_shared_id_refuses_before_remote_request(self):
        self.make_manifest(include_first=False)
        with patch.object(pilot, "api_call") as api:
            with self.assertRaisesRegex(review.LinkedReviewError, "both staged inventories"):
                self.inspect()
            api.assert_not_called()

    def test_staged_remote_missing_shared_id_refuses_before_remote_request(self):
        self.make_pull(include_first=False)
        with patch.object(pilot, "api_call") as api:
            with self.assertRaisesRegex(review.LinkedReviewError, "both staged inventories"):
                self.inspect()
            api.assert_not_called()

    def test_pending_source_refuses_before_remote_request(self):
        with sqlite3.connect(self.outbox_path) as db:
            db.execute("UPDATE sync_outbox SET state='pending'")
        with patch.object(pilot, "api_call") as api:
            with self.assertRaisesRegex(provenance.ProvenanceError, "acknowledged"):
                self.inspect()
            api.assert_not_called()

    def test_corrupt_baseline_digest_refuses_before_remote_request(self):
        with sqlite3.connect(self.pull_path) as db:
            db.execute("UPDATE pull_baseline_tasks SET version=100 WHERE id=?", (TASK,))
        with patch.object(pilot, "api_call") as api:
            with self.assertRaisesRegex(baseline.ReviewError, "digest mismatch"):
                self.inspect()
            api.assert_not_called()

    def test_rejects_unsafe_manifest_file_before_network(self):
        os.chmod(self.manifest_path, 0o644)
        with patch.object(pilot, "api_call") as api:
            with self.assertRaisesRegex(baseline.ReviewError, "0600"):
                self.inspect()
            api.assert_not_called()

    def test_digest_and_receipt_mutation_rejected_without_writes(self):
        bad = self.receipt()
        bad["source_payload_sha256"] = "f" * 64
        with patch.object(pilot, "api_call", return_value=bad):
            with self.assertRaisesRegex(provenance.ProvenanceError, "does not attest"):
                self.inspect()
        self.assertEqual(self.canonical_path.read_bytes(),
                         b"ORIGINAL CANONICAL TASKS - MUST REMAIN UNTOUCHED")

    def test_network_unavailable_does_not_change_journals(self):
        old_pull = self.pull_path.read_bytes()
        old_outbox = self.outbox_path.read_bytes()
        with patch.object(pilot, "api_call", side_effect=pilot.SyncPilotError("Receipt unavailable")):
            with self.assertRaisesRegex(pilot.SyncPilotError, "unavailable"):
                self.inspect()
        self.assertEqual(self.pull_path.read_bytes(), old_pull)
        self.assertEqual(self.outbox_path.read_bytes(), old_outbox)
        self.assertEqual(self.canonical_path.read_bytes(),
                         b"ORIGINAL CANONICAL TASKS - MUST REMAIN UNTOUCHED")


if __name__ == "__main__":
    unittest.main()
