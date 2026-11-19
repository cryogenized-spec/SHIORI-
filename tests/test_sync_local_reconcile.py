"""S6 real SQLite-shaped fixtures: no network or canonical task mutation."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare/shiori-mcp/scripts"))
import sync_local_reconcile as review
import sync_pull_preview as pull
import sync_import_pilot as pilot

DEVICE = "22222222-2222-4222-8222-222222222222"
TASK = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
RECEIPT = "88888888-8888-4888-8888-888888888888"
EVENT = f"sync1:{DEVICE}:{TASK}:1"
PRIVATE_TITLE = "CONFIDENTIAL CUSTOMER TASK"
PRIVATE_NOTES = "CONFIDENTIAL CUSTOMER NOTES"


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.canonical = self.root / "tasks.sqlite3"
        self.journal = self.root / "tasks.sync.sqlite3"
        self.shadow = self.root / "remote.pull-preview.sqlite3"
        self.payload = json.dumps({
            "schema_version": 1, "event_id": EVENT,
            "origin_device_id": DEVICE, "workspace_id": "personal",
            "task": {
                "id": TASK, "version": 1, "title": PRIVATE_TITLE,
                "notes": PRIVATE_NOTES, "status": "todo",
                "deleted_at": None,
            }, "depends_on": [],
        }, separators=(",", ":"))
        self.source_hash = hashlib.sha256(self.payload.encode()).hexdigest()
        self.create_canonical()
        self.create_outbox()
        self.stage_remote()
        self.before = self.canonical.read_bytes()

    def create_canonical(self):
        db = sqlite3.connect(self.canonical)
        db.executescript("""
            PRAGMA user_version=3;
            CREATE TABLE tasks(
                id TEXT PRIMARY KEY, title TEXT NOT NULL, notes TEXT NOT NULL,
                project TEXT NOT NULL, priority TEXT NOT NULL, status TEXT NOT NULL,
                due_on TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                completed_at TEXT, version INTEGER NOT NULL, deleted_at TEXT,
                estimate_minutes INTEGER, assignee_id TEXT
            );
            CREATE TABLE task_dependencies(
                task_id TEXT NOT NULL, depends_on_id TEXT NOT NULL,
                PRIMARY KEY(task_id,depends_on_id)
            );
        """)
        db.execute(
            "INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (TASK, PRIVATE_TITLE, PRIVATE_NOTES, "Personal", "medium", "todo",
             "2026-11-30", "2026-11-19T09:00:00Z",
             "2026-11-19T09:00:00Z", None, 1, None, 35, "local")
        )
        db.commit()
        db.close()
        os.chmod(self.canonical, 0o600)

    def create_outbox(self):
        db = sqlite3.connect(self.journal)
        db.executescript("""
            PRAGMA user_version=1;
            CREATE TABLE sync_meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE sync_outbox (
                event_id TEXT PRIMARY KEY,task_id TEXT,local_version INTEGER,
                payload_json TEXT,state TEXT,remote_id TEXT,remote_version INTEGER
            );
        """)
        db.execute("INSERT INTO sync_meta VALUES('device_id',?)", (DEVICE,))
        db.execute("INSERT INTO sync_outbox VALUES(?,?,?,?,?,?,?)", (
            EVENT, TASK, 1, self.payload, "acknowledged", TASK, 1,
        ))
        db.commit()
        db.close()
        os.chmod(self.journal, 0o600)

    def sample(self, version=1, status="todo", notes=PRIVATE_NOTES,
               deleted_at=None, depends=None, source=None):
        record = {
            "id": TASK, "title": PRIVATE_TITLE, "notes": notes,
            "project": "Personal", "status": status, "priority": "medium",
            "version": version, "created_at": "2026-11-19T09:00:00Z",
            "updated_at": "2026-11-19T09:00:00Z", "deleted_at": deleted_at,
        }
        original = {
            "receipt_id": RECEIPT, "source_event_id": EVENT,
            "source_version": 1, "source_payload_sha256": self.source_hash,
        }
        evidence = {
            "record": record, "depends_on": depends or [],
            "source_import": original if source is None else source,
            "cutoff": version,
        }
        digest = hashlib.sha256(
            json.dumps(evidence, ensure_ascii=False,
                       separators=(",", ":")).encode("utf8")
        ).hexdigest()
        return evidence, digest

    def stage_remote(self, **kwargs):
        if self.shadow.exists():
            self.shadow.unlink()
        evidence, digest = self.sample(**kwargs)
        self.assertTrue(pull.stage(self.shadow, evidence, digest))
        return evidence, digest

    def run_review(self):
        with patch.object(pilot, "api_call") as api:
            report = review.reconcile(
                self.canonical, self.shadow, self.journal, TASK, EVENT
            )
            api.assert_not_called()
        return report

    def test_exact_source_overlap_still_requires_fresh_owner_review(self):
        report = self.run_review()
        self.assertTrue(report["source_event_is_locally_acknowledged"])
        self.assertTrue(report["staged_s2_import_receipt_matches_local_source"])
        self.assertTrue(report["remote_snapshot_fingerprint_valid"])
        self.assertEqual(report["common_fields_different"], 0)
        self.assertTrue(report["dependency_graph_equal"])
        self.assertTrue(report["rust_only_fields_present"])
        self.assertEqual(report["canonical_local_revision"], 1)
        self.assertFalse(report["ready_for_apply"])
        self.assertFalse(report["safe_to_apply"])
        self.assertFalse(report["remote_snapshot_current_freshness_verified"])
        self.assertFalse(report["network_called"])
        self.assertFalse(report["canonical_rust_database_modified"])
        self.assertEqual(self.canonical.read_bytes(), self.before)
        console = json.dumps(report)
        for secret in (
            TASK, DEVICE, EVENT, RECEIPT, PRIVATE_TITLE, PRIVATE_NOTES,
            self.source_hash,
        ):
            self.assertNotIn(secret, console)

    def test_two_devices_disagree_on_same_field_and_revision_is_flagged(self):
        with sqlite3.connect(self.canonical) as db:
            db.execute(
                "UPDATE tasks SET notes=?,version=2 WHERE id=?",
                ("Local offline edit", TASK),
            )
        self.stage_remote(version=3, notes="Different cloud edit")
        report = self.run_review()
        self.assertEqual(report["canonical_local_revision"], 2)
        self.assertEqual(report["staged_remote_revision"], 3)
        self.assertEqual(report["common_fields_different"], 1)
        self.assertIn(
            "local-history-after-original-import", report["manual_review_blockers"]
        )
        self.assertIn(
            "remote-history-after-original-import", report["manual_review_blockers"]
        )

    def test_tombstones_are_not_resurrected(self):
        with sqlite3.connect(self.canonical) as db:
            db.execute(
                "UPDATE tasks SET deleted_at=?,version=2 WHERE id=?",
                ("2026-11-19T10:00:00Z", TASK),
            )
        self.stage_remote(version=3, deleted_at="2026-11-19T11:00:00Z")
        report = self.run_review()
        self.assertIn("local-tombstone-present", report["manual_review_blockers"])
        self.assertIn("remote-tombstone-present", report["manual_review_blockers"])
        self.assertFalse(report["ready_for_apply"])

    def test_dependency_mismatch_fails_manual_review(self):
        with sqlite3.connect(self.canonical) as db:
            db.execute(
                "INSERT INTO task_dependencies VALUES(?,?)", (TASK, OTHER)
            )
        report = self.run_review()
        self.assertFalse(report["dependency_graph_equal"])
        self.assertIn(
            "dependency-graph-disagreement", report["manual_review_blockers"]
        )

    def test_missing_canonical_task_not_assumed_remote_new(self):
        with sqlite3.connect(self.canonical) as db:
            db.execute("DELETE FROM tasks WHERE id=?", (TASK,))
        report = self.run_review()
        self.assertFalse(report["canonical_local_task_found"])
        self.assertIn("local-task-absent", report["manual_review_blockers"])
        self.assertFalse(report["ready_for_apply"])

    def test_wrong_or_pending_original_import_rejected(self):
        with sqlite3.connect(self.journal) as db:
            db.execute(
                "UPDATE sync_outbox SET state='pending' WHERE event_id=?", (EVENT,)
            )
        with self.assertRaisesRegex(Exception, "acknowledged"):
            self.run_review()
        with sqlite3.connect(self.journal) as db:
            db.execute(
                "UPDATE sync_outbox SET state='acknowledged',payload_json=?",
                (self.payload.replace(PRIVATE_NOTES, "CHANGED NOTE"),)
            )
        with self.assertRaisesRegex(review.ReconciliationError, "disagree"):
            self.run_review()

    def test_changed_stored_s4_digest_rejected(self):
        with sqlite3.connect(self.shadow) as db:
            db.execute(
                "UPDATE previews SET digest=? WHERE task_id=?",
                ("0" * 64, TASK),
            )
        with self.assertRaisesRegex(review.ReconciliationError, "hash-valid"):
            self.run_review()

    def test_unrecognized_preview_and_wrong_source_receipt_rejected(self):
        with sqlite3.connect(self.shadow) as db:
            db.execute(
                "UPDATE preview_meta SET value='unknown' WHERE key='kind'"
            )
        with self.assertRaisesRegex(review.ReconciliationError, "Unrecognized"):
            self.run_review()
        self.stage_remote(source={
            "receipt_id": RECEIPT, "source_event_id": EVENT,
            "source_version": 1, "source_payload_sha256": "0" * 64,
        })
        with self.assertRaisesRegex(review.ReconciliationError, "disagree"):
            self.run_review()

    def test_all_private_inputs_refuse_symlinks_and_world_readable_files(self):
        for attr in ("canonical", "shadow", "journal"):
            target = getattr(self, attr)
            alias = self.root / (attr + ".symlink")
            alias.symlink_to(target)
            old = getattr(self, attr)
            setattr(self, attr, alias)
            with self.subTest(kind="symlink", file=attr):
                with self.assertRaises(Exception):
                    self.run_review()
            setattr(self, attr, old)
            os.chmod(target, 0o644)
            with self.subTest(kind="permissions", file=attr):
                with self.assertRaises(Exception):
                    self.run_review()
            os.chmod(target, 0o600)

    def test_hardlink_alias_and_bad_schema_refused(self):
        self.shadow.unlink()
        os.link(self.canonical, self.shadow)
        with self.assertRaisesRegex(review.ReconciliationError, "share a file"):
            self.run_review()
        self.shadow.unlink()
        self.stage_remote()
        with sqlite3.connect(self.canonical) as db:
            db.execute("PRAGMA user_version=2")
        with self.assertRaisesRegex(review.ReconciliationError, "version 3"):
            self.run_review()


if __name__ == "__main__":
    unittest.main()
