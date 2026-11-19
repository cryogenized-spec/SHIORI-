"""S8 owner-controlled live S2/S4-to-Rust apply, synthetic proof checks only."""
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare/shiori-mcp/scripts"))
import sync_apply_owner as owner
import sync_import_pilot as pilot
from test_sync_local_reconcile import (
    ReconciliationTests, TASK, EVENT, RECEIPT, PRIVATE_TITLE, PRIVATE_NOTES,
)


class OwnerApplyTests(unittest.TestCase):
    def setUp(self):
        # Real SQLite-shaped fixture is shared with S6 tests. It never opens
        # a live connected account or the user's canonical task records.
        self.fixture = ReconciliationTests(
            methodName="test_exact_source_overlap_still_requires_fresh_owner_review"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.token = self.fixture.root / "owner-token"
        self.token.write_text("TEST_ONLY_OWNER_TOKEN", encoding="utf8")
        self.token.chmod(0o600)
        self.cli = Path("/bin/true")
        self.backup = self.fixture.root / "before.shiori-backup.sqlite3"

    def args(self, **extra):
        kw = {
            "canonical": self.fixture.canonical, "shadow": self.fixture.shadow,
            "outbox": self.fixture.journal, "token_file": self.token,
            "task_id": TASK, "event_id": EVENT, "confirmed_content": True,
        }
        kw.update(extra)
        return kw

    def network(self, *, revision=1, notes=PRIVATE_NOTES, change_digest=False,
                wrong_receipt=False, dependencies=None):
        obs, digest = self.fixture.sample(
            version=revision, notes=notes, depends=dependencies
        )
        if change_digest:
            obs["record"]["notes"] = "changed AFTER the owner staged S4"
        data = {**obs, "record_sha256": digest,
                "consistent_snapshot": True,
                "local_rust_sync": False, "automatic_apply": False}
        receipt = {
            "receipt_id": RECEIPT, "resource_id": TASK,
            "source_event_id": EVENT, "source_version": 1,
            "source_payload_sha256": self.fixture.source_hash
                if not wrong_receipt else "f" * 64,
            "remote_revision": revision, "remote_modified": revision != 1,
        }
        calls = []
        def handler(name, token, args):
            self.assertEqual(token, "TEST_ONLY_OWNER_TOKEN")
            calls.append((name, args))
            if name == "sync.import.receipt.read":
                self.assertEqual(args, {"event_id": EVENT})
                return receipt
            if name == "sync.record.snapshot.read":
                self.assertEqual(args, {
                    "task_id": TASK, "include_content": True
                })
                return data
            raise AssertionError("Unexpected remote operation")
        return handler, calls, data

    def test_preflight_returns_digest_and_counts_no_task_content_and_no_writes(self):
        handler, calls, data = self.network()
        with patch.object(pilot, "api_call", side_effect=handler), patch.object(
            owner, "_local_apply"
        ) as apply:
            result = owner.run(**self.args())
            apply.assert_not_called()
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["common_fields_to_review"], 0)
        self.assertEqual(result["remote_observation_sha256_to_approve"],
                         data["record_sha256"])
        self.assertFalse(result["local_apply_committed"])
        self.assertFalse(result["automatic_sync"])
        self.assertFalse(result["cloudflare_mutated"])
        self.assertFalse(self.backup.exists())
        self.assertEqual(self.fixture.canonical.read_bytes(), self.fixture.before)
        for secret in (PRIVATE_TITLE, PRIVATE_NOTES, TASK, EVENT, RECEIPT):
            self.assertNotIn(secret, json.dumps(result))

    def test_approval_without_exact_digest_is_rejected_before_apply(self):
        self.fixture.stage_remote(version=2, notes="Remote changed")
        handler, calls, data = self.network(revision=2, notes="Remote changed")
        with patch.object(pilot, "api_call", side_effect=handler), patch.object(
            owner, "_local_apply"
        ) as apply:
            with self.assertRaisesRegex(owner.ApplyError, "approval"):
                owner.run(**self.args(owner_approved=True,
                     approved_digest="a" * 64, cli=self.cli, backup=self.backup))
            apply.assert_not_called()
        self.assertEqual(self.fixture.canonical.read_bytes(), self.fixture.before)
        self.assertFalse(self.backup.exists())

    def test_confirmed_s2_s4_digest_bound_apply_has_post_commit_verification(self):
        self.fixture.stage_remote(version=2, notes="REMOTE REVIEWED NOTES")
        handler, calls, data = self.network(revision=2, notes="REMOTE REVIEWED NOTES")
        remote = data["record"]
        def fake_rust(cli, canonical, backup, local_ver, live):
            self.assertEqual(cli, self.cli)
            self.assertEqual(canonical, self.fixture.canonical)
            self.assertEqual(backup, self.backup)
            self.assertEqual(local_ver, 1)
            with sqlite3.connect(canonical) as db:
                db.execute(
                    "UPDATE tasks SET title=?,notes=?,project=?,priority=?,"
                    "status=?,version=version+1 WHERE id=? AND version=1",
                    (remote["title"], remote["notes"], remote["project"],
                     remote["priority"], remote["status"], TASK),
                )
            backup.write_bytes(b"MOCKED_RUST_BACKUP")
            return 0
        with patch.object(pilot, "api_call", side_effect=handler), patch.object(
            owner, "_local_apply", side_effect=fake_rust
        ) as apply:
            report = owner.run(**self.args(owner_approved=True,
                approved_digest=data["record_sha256"],
                backup=self.backup, cli=self.cli))
            apply.assert_called_once()
        self.assertTrue(report["local_apply_committed"])
        self.assertEqual(report["post_apply_local_revision"], 2)
        self.assertTrue(report["private_pre_apply_backup_created"])
        self.assertFalse(report["automatic_sync"])
        self.assertFalse(report["cloudflare_mutated"])
        self.assertNotIn("REMOTE REVIEWED NOTES", json.dumps(report))

    def test_s8_without_explicit_content_consent_never_contacts_network(self):
        with patch.object(pilot, "api_call") as remote:
            with self.assertRaisesRegex(owner.ApplyError, "confirm-read-content"):
                owner.run(**self.args(confirmed_content=False))
            remote.assert_not_called()

    def test_changed_local_common_content_blocks_even_with_owner_digest(self):
        self.fixture.stage_remote(version=2, notes="Remote edit")
        with sqlite3.connect(self.fixture.canonical) as db:
            db.execute("UPDATE tasks SET notes=?,version=2 WHERE id=?",
                       ("Different local edit", TASK))
        handler, calls, data = self.network(revision=2, notes="Remote edit")
        with patch.object(pilot, "api_call", side_effect=handler), patch.object(
            owner, "_local_apply"
        ) as apply:
            with self.assertRaisesRegex(owner.ApplyError, "changed since"):
                owner.run(**self.args(owner_approved=True,
                     approved_digest=data["record_sha256"],
                     backup=self.backup, cli=self.cli))
            apply.assert_not_called()
        self.assertEqual(calls, [], "Local conflicts must fail before any cloud call")

    def test_changed_remote_after_preview_or_forged_receipt_never_applies(self):
        self.fixture.stage_remote(version=2, notes="Staged remote")
        for change, wrong in ((True, False), (False, True)):
            handler, calls, data = self.network(
                revision=2, notes="Staged remote",
                change_digest=change, wrong_receipt=wrong
            )
            with self.subTest(change=change, wrong=wrong), patch.object(
                pilot, "api_call", side_effect=handler
            ), patch.object(owner, "_local_apply") as apply:
                with self.assertRaises(Exception):
                    owner.run(**self.args(owner_approved=True,
                        approved_digest=data["record_sha256"],
                        backup=self.backup, cli=self.cli))
                apply.assert_not_called()
                self.assertFalse(self.backup.exists())

    def test_graph_change_or_tombstone_fails_without_network(self):
        for opts in ({"depends": ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"]},
                     {"deleted_at": "2026-11-19T18:00:00Z"}):
            self.fixture.stage_remote(version=2, **opts)
            with self.subTest(options=opts), patch.object(
                pilot, "api_call"
            ) as remote:
                with self.assertRaises(owner.ApplyError):
                    owner.run(**self.args())
                remote.assert_not_called()

    def test_no_change_to_apply_cannot_create_unnecessary_backup(self):
        handler, calls, data = self.network()
        with patch.object(pilot, "api_call", side_effect=handler), patch.object(
            owner, "_local_apply"
        ) as apply:
            with self.assertRaisesRegex(owner.ApplyError, "No reviewed"):
                owner.run(**self.args(owner_approved=True,
                     approved_digest=data["record_sha256"],
                     backup=self.backup, cli=self.cli))
            apply.assert_not_called()

    def test_existing_backup_and_missing_cli_rejected_without_task_mutation(self):
        self.fixture.stage_remote(version=2, notes="Remote changed")
        handler, calls, data = self.network(revision=2, notes="Remote changed")
        self.backup.write_bytes(b"EXISTING BACKUP -- DO NOT OVERWRITE")
        with patch.object(pilot, "api_call", side_effect=handler), patch.object(
            owner, "_local_apply"
        ) as apply:
            with self.assertRaisesRegex(owner.ApplyError, "already exists"):
                owner.run(**self.args(owner_approved=True,
                    approved_digest=data["record_sha256"],
                    backup=self.backup, cli=self.cli))
            apply.assert_not_called()
        self.assertEqual(self.backup.read_bytes(),
                         b"EXISTING BACKUP -- DO NOT OVERWRITE")
        self.assertEqual(self.fixture.canonical.read_bytes(), self.fixture.before)

    def test_unverified_derived_private_file_or_token_never_reaches_cloud(self):
        self.token.chmod(0o644)
        with patch.object(pilot, "api_call") as network:
            with self.assertRaises(Exception):
                owner.run(**self.args())
            network.assert_not_called()

    def test_uncertain_post_write_state_reports_failure_not_success(self):
        self.fixture.stage_remote(version=2, notes="Remote changed")
        handler, calls, data = self.network(revision=2, notes="Remote changed")
        with patch.object(pilot, "api_call", side_effect=handler), patch.object(
            owner, "_local_apply", return_value=0
        ):
            with self.assertRaisesRegex(owner.ApplyError, "Post-apply"):
                owner.run(**self.args(owner_approved=True,
                    approved_digest=data["record_sha256"],
                    backup=self.backup, cli=self.cli))
        self.assertEqual(self.fixture.canonical.read_bytes(), self.fixture.before)


if __name__ == "__main__":
    unittest.main()
