"""Synthetic S3 provenance checks: no network, canonical task DB or task mutation."""
from contextlib import redirect_stdout
from io import StringIO
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
import sync_provenance_check as check
import sync_import_pilot as pilot

DEVICE = "22222222-2222-4222-8222-222222222222"
TASK = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
RECEIPT = "88888888-8888-4888-8888-888888888888"
EVENT = f"sync1:{DEVICE}:{TASK}:1"
PRIVATE_TITLE = "DO NOT PRINT THIS CUSTOMER TITLE"
PRIVATE_NOTES = "DO NOT PRINT THIS CUSTOMER NOTE"


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.journal = self.root / "tasks.sync.sqlite3"
        self.token = self.root / "owner-token"
        self.canonical = self.root / "tasks.sqlite3"
        self.canonical.write_bytes(b"CANONICAL USER RECORDS ARE OUT OF SCOPE")
        self.payload = json.dumps({
            "schema_version": 1, "event_id": EVENT, "origin_device_id": DEVICE,
            "workspace_id": "personal",
            "task": {
                "id": TASK, "version": 1, "title": PRIVATE_TITLE, "notes": PRIVATE_NOTES,
                "status": "todo", "deleted_at": None
            },
            "depends_on": []
        }, separators=(",", ":"))
        self.sha = hashlib.sha256(self.payload.encode()).hexdigest()
        db = sqlite3.connect(self.journal)
        db.executescript("""
          PRAGMA user_version=1;
          CREATE TABLE sync_meta (key TEXT PRIMARY KEY, value TEXT);
          CREATE TABLE sync_outbox(
             event_id TEXT PRIMARY KEY, task_id TEXT, local_version INTEGER,
             payload_json TEXT, state TEXT, remote_id TEXT, remote_version INTEGER
          );
        """)
        db.execute("INSERT INTO sync_meta VALUES('device_id',?)", (DEVICE,))
        db.execute("INSERT INTO sync_outbox VALUES(?,?,?,?,?,?,?)",
                   (EVENT, TASK, 1, self.payload, "acknowledged", TASK, 1))
        db.commit()
        db.close()
        os.chmod(self.journal, 0o600)
        self.token.write_text("SYNTHETIC_BEARER_TOKEN", encoding="utf-8")
        os.chmod(self.token, 0o600)

    def receipt(self, revision=1):
        return {"receipt_id": RECEIPT, "resource_id": TASK,
                "source_event_id": EVENT, "source_version": 1,
                "remote_revision": revision, "source_payload_sha256": self.sha,
                "remote_modified": revision != 1}

    def test_verifies_only_receipt_metadata_and_leaves_canonical_untouched(self):
        with patch.object(pilot, "api_call", return_value=self.receipt()) as remote:
            out = StringIO()
            with redirect_stdout(out):
                report = check.verify(self.journal, self.token, EVENT)
                print(json.dumps(report))
        remote.assert_called_once_with(
            "sync.import.receipt.read", "SYNTHETIC_BEARER_TOKEN", {"event_id": EVENT})
        self.assertTrue(report["s2_source_provenance_confirmed"])
        self.assertFalse(report["local_rust_sync"])
        self.assertFalse(report["safe_to_apply"])
        self.assertFalse(report["task_content_transferred"])
        self.assertFalse(report["local_or_remote_task_writes"])
        self.assertTrue(report["other_task_identities_unverified"])
        self.assertEqual(self.canonical.read_bytes(), b"CANONICAL USER RECORDS ARE OUT OF SCOPE")
        for secret in (PRIVATE_TITLE, PRIVATE_NOTES, TASK, EVENT, DEVICE, self.sha):
            self.assertNotIn(secret, out.getvalue())

    def test_later_remote_revision_preserves_provenance_but_not_convergence(self):
        with patch.object(pilot, "api_call", return_value=self.receipt(revision=4)):
            report = check.verify(self.journal, self.token, EVENT)
        self.assertTrue(report["s2_source_provenance_confirmed"])
        self.assertTrue(report["remote_modified_since_import"])
        self.assertEqual(report["remote_observed_revision"], 4)
        self.assertFalse(report["safe_to_apply"])

    def test_forged_remote_receipt_hash_and_identity_fail_closed(self):
        fields = ("source_payload_sha256", "resource_id", "source_event_id",
                  "remote_revision", "receipt_id", "remote_modified", "source_version")
        for field in fields:
            payload = self.receipt()
            payload[field] = {
                "source_payload_sha256": "0" * 64,
                "resource_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
                "source_event_id": "wrong-sync-event",
                "remote_revision": 2,
                "receipt_id": "not-a-uuid",
                "remote_modified": True,
                "source_version": 2,
            }[field]
            with self.subTest(field=field):
                with patch.object(pilot, "api_call", return_value=payload):
                    with self.assertRaisesRegex(check.ProvenanceError, "does not attest"):
                        check.verify(self.journal, self.token, EVENT)

    def test_rejects_unexpected_remote_content_without_printing_it(self):
        payload = self.receipt()
        payload["notes"] = PRIVATE_NOTES
        with patch.object(pilot, "api_call", return_value=payload):
            with self.assertRaisesRegex(check.ProvenanceError, "Unexpected remote receipt fields"):
                check.verify(self.journal, self.token, EVENT)

    def test_unacknowledged_or_conflicted_source_does_not_contact_cloud(self):
        for state in ("pending", "conflict"):
            with sqlite3.connect(self.journal) as db:
                db.execute("UPDATE sync_outbox SET state=? WHERE event_id=?", (state, EVENT))
            with self.subTest(state=state), patch.object(pilot, "api_call") as remote:
                with self.assertRaisesRegex(check.ProvenanceError, "acknowledged"):
                    check.verify(self.journal, self.token, EVENT)
                remote.assert_not_called()

    def test_tampered_source_payload_fails_remote_digest_check(self):
        with sqlite3.connect(self.journal) as db:
            db.execute("UPDATE sync_outbox SET payload_json=REPLACE(payload_json,?,?)",
                       (PRIVATE_NOTES, "ALTERED PRIVATE NOTE"))
        with patch.object(pilot, "api_call", return_value=self.receipt()):
            with self.assertRaisesRegex(check.ProvenanceError, "does not attest"):
                check.verify(self.journal, self.token, EVENT)

    def test_local_identity_and_ack_revision_tampering_rejected_pre_network(self):
        for sql in (
            "UPDATE sync_outbox SET remote_id='different' WHERE event_id=?",
            "UPDATE sync_outbox SET local_version=2 WHERE event_id=?",
            "UPDATE sync_outbox SET remote_version=2 WHERE event_id=?",
        ):
            with sqlite3.connect(self.journal) as db:
                db.execute("UPDATE sync_outbox SET remote_id=?,local_version=1,remote_version=1",
                           (TASK,))
                db.execute(sql, (EVENT,))
            with self.subTest(sql=sql), patch.object(pilot, "api_call") as remote:
                with self.assertRaisesRegex(check.ProvenanceError, "disagree"):
                    check.verify(self.journal, self.token, EVENT)
                remote.assert_not_called()

    def test_token_and_journal_must_be_private(self):
        os.chmod(self.token, 0o644)
        with patch.object(pilot, "api_call") as remote:
            with self.assertRaisesRegex(pilot.SyncPilotError, "non-private"):
                check.verify(self.journal, self.token, EVENT)
            remote.assert_not_called()
        os.chmod(self.token, 0o600)
        alias = self.root / "link"
        alias.symlink_to(self.journal)
        with patch.object(pilot, "api_call") as remote:
            with self.assertRaisesRegex(pilot.SyncPilotError, "non-private"):
                check.verify(alias, self.token, EVENT)
            remote.assert_not_called()

    def test_network_error_never_modifies_local_acknowledgement(self):
        with patch.object(pilot, "api_call", side_effect=pilot.SyncPilotError("HTTPS receipt unavailable")):
            with self.assertRaisesRegex(pilot.SyncPilotError, "unavailable"):
                check.verify(self.journal, self.token, EVENT)
        with sqlite3.connect(self.journal) as db:
            row = db.execute("SELECT state,remote_version,payload_json FROM sync_outbox").fetchone()
        self.assertEqual(row, ("acknowledged", 1, self.payload))
        self.assertEqual(self.canonical.read_bytes(), b"CANONICAL USER RECORDS ARE OUT OF SCOPE")


if __name__ == "__main__":
    unittest.main()
