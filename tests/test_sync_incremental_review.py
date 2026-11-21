"""S10 synthetic checkpoint-cycle comparisons: two-device stale edits, no writes."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare/shiori-mcp/scripts"))
import sync_incremental_review as incremental
import sync_import_pilot as pilot
from test_sync_revision_checkpoint import RevisionCheckpointTests, TASK, EVENT


class IncrementalReviewTests(unittest.TestCase):
    def setUp(self):
        self.fx = RevisionCheckpointTests(
            methodName="test_post_apply_one_task_checkpoint_is_private_and_metadata_only"
        )
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.fx.run_stage()
        self.canonical = self.fx.canonical
        self.backup = self.fx.backup
        self.shadow = self.fx.shadow
        self.journal = self.fx.outbox
        self.token = self.fx.token
        self.checkpoint = self.fx.checkpoint
        self.canonical_before = self.canonical.read_bytes()
        self.checkpoint_before = self.checkpoint.read_bytes()

    def args(self, **extra):
        args = {
            "canonical": self.canonical, "shadow": self.shadow,
            "journal": self.journal, "token_file": self.token,
            "checkpoint_file": self.checkpoint, "task_id": TASK,
            "event_id": EVENT, "confirmed_content": True,
        }
        args.update(extra)
        return args

    def remote(self, *, version=2, notes="Reviewed new cloud note",
               deleted_at=None, depends=None, cutoff=None, wrong_receipt=False):
        handler, calls, data = self.fx.fx.network(
            revision=version, notes=notes, wrong_receipt=wrong_receipt,
            dependencies=depends,
        )
        if cutoff is not None:
            data["cutoff"] = cutoff
        if deleted_at is not None:
            data["record"]["deleted_at"] = deleted_at
        evidence = {
            key: data[key] for key in ("record", "depends_on", "source_import", "cutoff")
        }
        data["record_sha256"] = hashlib.sha256(json.dumps(
            evidence, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()
        return handler, calls, data

    def run_review(self, **options):
        handler, calls, data = self.remote(**options)
        with patch.object(pilot, "api_call", side_effect=handler):
            result = incremental.review(**self.args())
        return result, calls

    def test_aligned_checkpoint_and_unrelated_cloud_cutoff_are_not_task_edits(self):
        report, calls = self.run_review()
        self.assertEqual(report["status"], "aligned_at_current_owner_read")
        self.assertFalse(report["local_common_fields_changed"])
        self.assertFalse(report["remote_common_fields_changed"])
        self.assertFalse(report["safe_to_apply"])
        self.assertFalse(report["automatic_sync"])
        self.assertEqual(len(calls), 2)
        report, _ = self.run_review(cutoff=55)
        self.assertEqual(report["status"], "aligned_at_current_owner_read")
        self.assertTrue(report["only_global_changefeed_cutoff_advanced"])
        self.assertEqual(self.canonical.read_bytes(), self.canonical_before)
        self.assertEqual(self.checkpoint.read_bytes(), self.checkpoint_before)
        for secret in (TASK, EVENT, "Reviewed new cloud note"):
            self.assertNotIn(secret, json.dumps(report))

    def test_remote_only_edit_requires_owner_review_not_automatic_pull(self):
        report, _ = self.run_review(version=3, notes="Changed on second device")
        self.assertEqual(report["status"], "remote_only_change_for_owner_review")
        self.assertFalse(report["local_common_fields_changed"])
        self.assertTrue(report["remote_common_fields_changed"])
        self.assertTrue(report["owner_review_required_before_any_apply"])
        self.assertFalse(report["local_rust_database_modified"])
        self.assertEqual(self.checkpoint.read_bytes(), self.checkpoint_before)

    def test_local_only_edit_requires_owner_review_not_automatic_push(self):
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE tasks SET notes=?,version=3 WHERE id=?",
                       ("Changed while offline", TASK))
        report, _ = self.run_review()
        self.assertEqual(report["status"], "local_only_change_for_owner_review")
        self.assertTrue(report["local_common_fields_changed"])
        self.assertFalse(report["remote_common_fields_changed"])
        self.assertFalse(report["cloudflare_database_modified"])

    def test_two_device_overlapping_content_conflict_never_last_write_wins(self):
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE tasks SET notes=?,version=3 WHERE id=?",
                       ("Different offline task content", TASK))
        report, _ = self.run_review(version=3, notes="Other device edit")
        self.assertEqual(report["status"], "two_sided_content_conflict")
        self.assertTrue(report["conflict_requires_manual_resolution"])
        self.assertFalse(report["safe_to_apply"])

    def test_deleted_local_or_remote_never_resurrected(self):
        report, _ = self.run_review(
            version=3, deleted_at="2026-11-19T18:30:00Z"
        )
        self.assertEqual(report["status"], "delete_conflict")
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE tasks SET deleted_at=?,version=3 WHERE id=?",
                       ("2026-11-19T18:20:00Z", TASK))
        report, _ = self.run_review()
        self.assertEqual(report["status"], "delete_conflict")

    def test_remote_dependency_mutation_without_common_task_revision_is_conflict(self):
        report, _ = self.run_review(
            version=3, depends=["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"]
        )
        self.assertEqual(report["status"], "dependency_conflict")
        self.assertTrue(report["remote_dependency_graph_changed"])

    def test_local_dependency_mutation_requires_manual_graph_review(self):
        with sqlite3.connect(self.canonical) as db:
            db.execute("INSERT INTO task_dependencies VALUES(?,?)",(
                TASK,"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            ))
        report, _ = self.run_review()
        self.assertEqual(report["status"], "dependency_conflict")
        self.assertTrue(report["local_dependency_graph_changed"])

    def test_same_revision_edited_content_is_untrusted_mutation(self):
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE tasks SET title=? WHERE id=?",
                       ("Unversioned silent local edit", TASK))
        report, _ = self.run_review()
        self.assertEqual(report["status"], "unversioned_mutation_conflict")
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE tasks SET title=? WHERE id=?",
                       ("Local before checkpoint", TASK))
            db.execute("UPDATE tasks SET title=? WHERE id=?",
                       ("CONFIDENTIAL CUSTOMER TASK", TASK))
        report, _ = self.run_review(version=2, notes="Silent remote edit")
        self.assertEqual(report["status"], "unversioned_mutation_conflict")

    def test_remote_timestamp_change_without_version_is_untrusted(self):
        handler, _, data = self.remote()
        data["record"]["updated_at"] = "2026-11-19T23:00:00Z"
        observation = {
            key: data[key] for key in (
                "record", "depends_on", "source_import", "cutoff"
            )
        }
        data["record_sha256"] = hashlib.sha256(json.dumps(
            observation, ensure_ascii=False, separators=(",", ":")
        ).encode()).hexdigest()
        with patch.object(pilot, "api_call", side_effect=handler):
            report = incremental.review(**self.args())
        self.assertEqual(report["status"], "unversioned_mutation_conflict")
        self.assertFalse(report["only_global_changefeed_cutoff_advanced"])

    def test_regressed_global_cutoff_rejected_even_without_field_changes(self):
        handler, _, _ = self.remote(cutoff=1)
        with patch.object(pilot, "api_call", side_effect=handler):
            with self.assertRaisesRegex(
                incremental.DivergenceError, "cutoff regressed"
            ):
                incremental.review(**self.args())

    def test_revision_advanced_without_common_field_change_requires_review(self):
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE tasks SET estimate_minutes=41,version=3 WHERE id=?",
                       (TASK,))
        report, _ = self.run_review()
        self.assertEqual(report["status"], "revision_without_common_content_change")
        self.assertTrue(report["owner_review_required_before_any_apply"])

    def test_checkpoint_tampering_or_regression_fails_closed_before_network(self):
        with sqlite3.connect(self.checkpoint) as db:
            db.execute("UPDATE checkpoints SET local_common_sha256=? WHERE task_id=?",
                       ("0" * 64, TASK))
        with patch.object(pilot, "api_call") as remote:
            with self.assertRaises(incremental.DivergenceError):
                incremental.review(**self.args())
            remote.assert_not_called()
        # Restore the source common-fields digest, never the full S4 observation.
        import sync_revision_checkpoint as ck
        with sqlite3.connect(self.checkpoint) as db:
            db.execute("UPDATE checkpoints SET local_common_sha256=? WHERE task_id=?",
                       (ck._common_hash(self.fx.remote["record"]), TASK))
        with sqlite3.connect(self.canonical) as db:
            db.execute("UPDATE tasks SET version=1 WHERE id=?", (TASK,))
        with patch.object(pilot, "api_call") as remote:
            with self.assertRaisesRegex(
                incremental.DivergenceError, "regressed"
            ):
                incremental.review(**self.args())
            remote.assert_not_called()

    def test_false_consent_and_insecure_token_never_perform_remote_read(self):
        with patch.object(pilot, "api_call") as remote:
            with self.assertRaisesRegex(
                incremental.DivergenceError, "confirm"
            ):
                incremental.review(**self.args(confirmed_content=False))
            remote.assert_not_called()
        self.token.chmod(0o644)
        with patch.object(pilot, "api_call") as remote:
            with self.assertRaises(Exception):
                incremental.review(**self.args())
            remote.assert_not_called()

    def test_forged_owner_receipt_blocks_live_content_reconciliation(self):
        handler, _, _ = self.remote(wrong_receipt=True)
        with patch.object(pilot, "api_call", side_effect=handler):
            with self.assertRaises(Exception):
                incremental.review(**self.args())


if __name__ == "__main__":
    unittest.main()
