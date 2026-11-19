"""S9 checkpoint acceptance: synthetic S8 after-state and owner-authenticated reads."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare/shiori-mcp/scripts"))
import sync_revision_checkpoint as ck
import sync_import_pilot as pilot
from test_sync_apply_owner import OwnerApplyTests, TASK, EVENT


class RevisionCheckpointTests(unittest.TestCase):
    def setUp(self):
        self.fx = OwnerApplyTests(
            methodName="test_preflight_returns_digest_and_counts_no_task_content_and_no_writes"
        )
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.canonical = self.fx.fixture.canonical
        self.shadow = self.fx.fixture.shadow
        self.outbox = self.fx.fixture.journal
        self.token = self.fx.token
        self.backup = self.fx.fixture.root / "pre-apply.shiori-backup.sqlite3"
        self.checkpoint = self.fx.fixture.root / "device.sync-checkpoint.sqlite3"
        with sqlite3.connect(self.canonical) as source:
            with sqlite3.connect(self.backup) as dest:
                source.backup(dest)
        os.chmod(self.backup, 0o600)
        self.fx.fixture.stage_remote(version=2, notes="Reviewed new cloud note")
        with sqlite3.connect(self.canonical) as db:
            db.execute(
                "UPDATE tasks SET notes=?,version=2 WHERE id=? AND version=1",
                ("Reviewed new cloud note", TASK),
            )
        self.after = self.canonical.read_bytes()
        self.network, self.calls, self.remote = self.fx.network(
            revision=2, notes="Reviewed new cloud note"
        )

    def run_stage(self, **kw):
        args = dict(canonical=self.canonical, backup=self.backup,
                    shadow=self.shadow, outbox=self.outbox,
                    token_file=self.token, checkpoint=self.checkpoint,
                    task_id=TASK, event_id=EVENT, owner_confirmed=True)
        args.update(kw)
        with patch.object(pilot, "api_call", side_effect=self.network):
            return ck.stage(**args)

    def test_post_apply_one_task_checkpoint_is_private_and_metadata_only(self):
        report = self.run_stage()
        self.assertTrue(report["checkpoint_recorded"])
        self.assertEqual(report["local_revision"], 2)
        self.assertEqual(report["remote_revision_at_read"], 2)
        self.assertTrue(report["original_s2_provenance_verified"])
        self.assertFalse(report["canonical_rust_database_modified"])
        self.assertFalse(report["continuous_two_way_sync"])
        self.assertEqual(self.canonical.read_bytes(), self.after)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(os.stat(self.checkpoint).st_mode & 0o077, 0)
        with sqlite3.connect(self.checkpoint) as db:
            row = db.execute("SELECT remote_version,local_version,"
                             "remote_record_sha256,local_common_sha256 "
                             "FROM checkpoints WHERE task_id=?", (TASK,)).fetchone()
            self.assertEqual(row[:2], (2, 2))
            self.assertEqual(row[2], self.remote["record_sha256"])
            self.assertEqual(len(row[3]), 64)
            content = db.execute("SELECT name FROM sqlite_master").fetchall()
        self.assertNotIn("Reviewed new cloud note", self.checkpoint.read_bytes().decode(
            "utf8", "ignore"
        ))
        for secret in (TASK, EVENT, "Reviewed new cloud note"):
            self.assertNotIn(secret, json.dumps(report))

    def test_same_receipt_idempotent_refuses_divergent_revision(self):
        self.run_stage()
        repeated = self.run_stage()
        self.assertFalse(repeated["checkpoint_recorded"])
        self.assertTrue(repeated["same_checkpoint_idempotent"])
        old_copy = self.checkpoint.read_bytes()
        with sqlite3.connect(self.checkpoint) as db:
            db.execute("UPDATE checkpoints SET remote_version=99")
        with self.assertRaisesRegex(ck.CheckpointError, "different mapping"):
            self.run_stage()
        self.assertTrue(self.checkpoint.exists())
        self.assertNotEqual(self.checkpoint.read_bytes(), old_copy)
        self.assertEqual(self.canonical.read_bytes(), self.after)

    def test_consent_required_before_token_or_network_or_file(self):
        with patch.object(pilot, "api_call") as network:
            with self.assertRaisesRegex(ck.CheckpointError, "confirm-checkpoint"):
                ck.stage(
                    self.canonical, self.backup, self.shadow, self.outbox,
                    self.token, self.checkpoint, TASK, EVENT,
                    owner_confirmed=False
                )
            network.assert_not_called()
        self.assertFalse(self.checkpoint.exists())

    def test_backup_is_required_and_cannot_alias_main_or_token_file(self):
        for backup in (self.canonical, self.token, self.shadow):
            with self.subTest(backup=backup.name):
                with self.assertRaises(Exception):
                    self.run_stage(backup=backup)
                self.assertFalse(self.checkpoint.exists())

    def test_stale_owner_snapshot_or_forged_receipt_block_checkpoint(self):
        for altered, wrong in ((True, False), (False, True)):
            self.network, _, _ = self.fx.network(
                revision=2, notes="Reviewed new cloud note",
                change_digest=altered, wrong_receipt=wrong
            )
            with self.subTest(altered=altered, wrong=wrong):
                with self.assertRaises(Exception):
                    self.run_stage()
                self.assertFalse(self.checkpoint.exists())

    def test_backup_changed_after_apply_is_not_accepted(self):
        with sqlite3.connect(self.backup) as db:
            db.execute("UPDATE tasks SET title=? WHERE id=?",
                       ("Fake previous task", TASK))
        with self.assertRaisesRegex(ck.CheckpointError, "baseline"):
            self.run_stage()
        self.assertFalse(self.checkpoint.exists())

    def test_same_local_revision_not_evidence_of_applied_remote_changes(self):
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE tasks SET version=1 WHERE id=?", (TASK,))
        with self.assertRaisesRegex(ck.CheckpointError, "baseline"):
            self.run_stage()

    def test_changed_rust_only_fields_are_rejected_as_s8_side_effect(self):
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE tasks SET estimate_minutes=99 WHERE id=?", (TASK,))
        with self.assertRaisesRegex(ck.CheckpointError, "Rust-only"):
            self.run_stage()
        self.assertFalse(self.checkpoint.exists())

    def test_wrong_private_file_mode_and_checkpoint_symlink_denied(self):
        self.backup.chmod(0o644)
        with self.assertRaises(Exception):
            self.run_stage()
        self.backup.chmod(0o600)
        alias = self.fx.fixture.root / "unrelated-file"
        alias.write_text("DO NOT CLOBBER", encoding="utf8")
        self.checkpoint.symlink_to(alias)
        with self.assertRaises(ck.CheckpointError):
            self.run_stage()
        self.assertEqual(alias.read_text(), "DO NOT CLOBBER")

    def test_stale_dependency_graph_requires_manual_conflict(self):
        self.fx.fixture.stage_remote(
            version=2, notes="Reviewed new cloud note",
            depends=["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"]
        )
        with self.assertRaisesRegex(ck.CheckpointError, "graph"):
            self.run_stage()
        self.assertFalse(self.checkpoint.exists())

    def test_corrupted_backup_sqlite_is_not_treated_as_restorable_evidence(self):
        self.backup.write_bytes(b"INVALID BACKUP DATA")
        with self.assertRaises(Exception):
            self.run_stage()
        self.assertFalse(self.checkpoint.exists())


if __name__ == "__main__":
    unittest.main()
