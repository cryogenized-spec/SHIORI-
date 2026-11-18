"""S4 isolated remote pull preview: synthetic owner content, no real network."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare/shiori-mcp/scripts"))
import sync_pull_preview as preview
import sync_import_pilot as pilot
import sync_review as review

TASK = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
NOTE = "PRIVATE customer notes not for standard console output"


def sample(*, version=1, title="Fixture task", notes=NOTE, deleted_at=None,
           depends=None, source=None):
    record = {
        "id": TASK, "title": title, "notes": notes, "project": "Fixtures",
        "status": "todo", "priority": "medium", "version": version,
        "created_at": "2026-11-18T11:00:00Z",
        "updated_at": "2026-11-18T11:00:00Z",
        "deleted_at": deleted_at,
    }
    evidence = {"record": record, "depends_on": [] if depends is None else depends,
                "source_import": source, "cutoff": version}
    raw = json.dumps(evidence, ensure_ascii=False, separators=(",", ":")).encode("utf8")
    return {**evidence, "record_sha256": hashlib.sha256(raw).hexdigest(),
            "consistent_snapshot": True, "local_rust_sync": False,
            "automatic_apply": False}


class PullPreviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.token = self.root / "private-token"
        self.token.write_text("SYNTHETIC_ONLY", encoding="utf8")
        os.chmod(self.token, 0o600)
        self.shadow = self.root / "one.pull-preview.sqlite3"
        self.canonical = self.root / "tasks.sqlite3"
        self.canonical.write_bytes(b"CANONICAL DATA MUST NOT CHANGE")

    def opts(self, *, confirmed=True, snapshot=None):
        with patch.object(pilot, "api_call", return_value=snapshot or sample()) as api:
            result = preview.pull(TASK, self.token, self.shadow, confirmed=confirmed)
        return result, api

    def test_explicit_content_confirmation_required_before_token_or_cloud(self):
        with patch.object(pilot, "api_call") as api:
            with self.assertRaisesRegex(preview.PullPreviewError, "confirm-read-content"):
                preview.pull(TASK, self.token, self.shadow, confirmed=False)
            api.assert_not_called()
        self.assertFalse(self.shadow.exists())

    def test_one_owner_snapshot_staged_without_canonical_mutation(self):
        result, api = self.opts()
        api.assert_called_once_with("sync.record.snapshot.read", "SYNTHETIC_ONLY", {
            "task_id": TASK, "include_content": True
        })
        self.assertTrue(result["private_preview_staged"])
        self.assertTrue(result["unknown_local_inventory"])
        self.assertFalse(result["safe_to_apply"])
        self.assertFalse(result["canonical_rust_database_modified"])
        self.assertEqual(stat.S_IMODE(self.shadow.stat().st_mode), 0o600)
        self.assertEqual(self.canonical.read_bytes(), b"CANONICAL DATA MUST NOT CHANGE")
        with sqlite3.connect(self.shadow) as db:
            payload = db.execute("SELECT observation_json FROM previews").fetchone()[0]
            self.assertEqual(json.loads(payload)["record"]["notes"], NOTE)
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertNotIn(NOTE, json.dumps(result))
        self.assertNotIn(TASK, json.dumps(result))

    def test_same_digest_repeat_is_idempotent_and_changed_remote_is_conflict(self):
        self.opts()
        repeated, _ = self.opts()
        self.assertFalse(repeated["private_preview_staged"])
        self.assertTrue(repeated["repeat_read_idempotent"])
        newer = sample(version=2, title="New edit")
        with patch.object(pilot, "api_call", return_value=newer):
            with self.assertRaisesRegex(preview.PullPreviewError, "no overwrite"):
                preview.pull(TASK, self.token, self.shadow, confirmed=True)
        with sqlite3.connect(self.shadow) as db:
            source = json.loads(db.execute("SELECT observation_json FROM previews").fetchone()[0])
        self.assertEqual(source["record"]["version"], 1)
        self.assertEqual(self.canonical.read_bytes(), b"CANONICAL DATA MUST NOT CHANGE")

    def test_forged_hash_missing_fields_and_wrong_id_fail_before_staging(self):
        for which in ("digest", "record", "foreign", "syncflag", "prerequisite"):
            bad = sample()
            if which == "digest":
                bad["record_sha256"] = "f" * 64
            elif which == "record":
                del bad["record"]["notes"]
            elif which == "foreign":
                bad["record"]["id"] = OTHER
            elif which == "syncflag":
                bad["automatic_apply"] = True
            else:
                bad["depends_on"] = [OTHER, OTHER]
            with self.subTest(which=which):
                with patch.object(pilot, "api_call", return_value=bad):
                    with self.assertRaises(preview.PullPreviewError):
                        preview.pull(TASK, self.token, self.shadow, confirmed=True)
                self.assertFalse(self.shadow.exists())

    def test_snapshot_unicode_notes_and_prior_import_receipt_remain_private(self):
        origin = {"receipt_id": "88888888-8888-4888-8888-888888888888",
                  "source_event_id": "sync1:owner:task:1",
                  "source_version": 1, "source_payload_sha256": "e" * 64}
        result, _ = self.opts(snapshot=sample(notes="Søren 👋 – 日本語", source=origin))
        self.assertTrue(result["historical_s2_receipt_present"])
        self.assertTrue(result["source_lineage_unverified"])
        self.assertFalse(result["safe_to_apply"])

    def test_soft_delete_and_dependencies_flagged_but_never_applied(self):
        result, _ = self.opts(snapshot=sample(version=3,
             deleted_at="2026-11-18T12:00:00Z", depends=[OTHER]))
        self.assertTrue(result["remote_tombstone_present"])
        self.assertEqual(result["remote_observed_revision"], 3)
        self.assertFalse(result["automatic_sync"])
        self.assertEqual(self.canonical.read_bytes(), b"CANONICAL DATA MUST NOT CHANGE")

    def test_refuses_world_readable_token_shadow_and_symlink(self):
        os.chmod(self.token, 0o644)
        with patch.object(pilot, "api_call") as api:
            with self.assertRaisesRegex(pilot.SyncPilotError, "non-private"):
                preview.pull(TASK, self.token, self.shadow, confirmed=True)
            api.assert_not_called()
        os.chmod(self.token, 0o600)
        self.opts()
        os.chmod(self.shadow, 0o644)
        with patch.object(pilot, "api_call") as api:
            with self.assertRaisesRegex(preview.PullPreviewError, "private"):
                preview.pull(TASK, self.token, self.shadow, confirmed=True)
            api.assert_not_called()
        os.chmod(self.shadow, 0o600)
        link = self.root / "alias.pull-preview.sqlite3"
        link.symlink_to(self.shadow)
        with patch.object(pilot, "api_call") as api:
            with self.assertRaisesRegex(preview.PullPreviewError, "symlink"):
                preview.pull(TASK, self.token, link, confirmed=True)
            api.assert_not_called()

    def test_never_confuses_canonical_or_outbox_with_preview(self):
        for path in (self.canonical, self.root / "tasks.sync.sqlite3", self.token):
            with patch.object(pilot, "api_call") as api:
                with self.assertRaisesRegex(preview.PullPreviewError, "dedicated"):
                    preview.pull(TASK, self.token, path, confirmed=True)
                api.assert_not_called()

    def test_preexisting_fake_sqlite_and_no_network_refuse_without_deletion(self):
        self.shadow.write_bytes(b"not a sqlite database")
        os.chmod(self.shadow, 0o600)
        data = self.shadow.read_bytes()
        with patch.object(pilot, "api_call", return_value=sample()):
            with self.assertRaises(preview.PullPreviewError):
                preview.pull(TASK, self.token, self.shadow, confirmed=True)
        self.assertEqual(self.shadow.read_bytes(), data)

    def test_two_independent_device_previews_cannot_overwrite_diverged_states(self):
        other_shadow = self.root / "second.pull-preview.sqlite3"
        with patch.object(pilot, "api_call", return_value=sample()):
            preview.pull(TASK, self.token, self.shadow, confirmed=True)
            preview.pull(TASK, self.token, other_shadow, confirmed=True)
        with patch.object(pilot, "api_call", return_value=sample(version=2, title="Changed in cloud")):
            with self.assertRaisesRegex(preview.PullPreviewError, "no overwrite"):
                preview.pull(TASK, self.token, other_shadow, confirmed=True)
        with sqlite3.connect(self.shadow) as a, sqlite3.connect(other_shadow) as b:
            self.assertEqual(a.execute("SELECT digest FROM previews").fetchone(),
                             b.execute("SELECT digest FROM previews").fetchone())


if __name__ == "__main__":
    unittest.main()
