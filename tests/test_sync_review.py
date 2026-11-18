"""Offline S3 review tests; uses synthetic files, no account, network or task DB."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import struct
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cloudflare/shiori-mcp/scripts"))
import sync_review as review


def manifest(entries):
    out = bytearray(review.MARKER)
    for row in entries:
        for cell in row:
            raw = cell.encode("utf-8")
            out.extend(struct.pack(">I", len(raw)))
            out.extend(raw)
    return bytes(out)


def baseline(cutoff=7):
    return {
        "items": [
            {"id": "task-a", "version": 2, "status": "todo", "updated_at": "2026-11-18T10:00:00Z", "deleted_at": None},
            {"id": "task-b", "version": 3, "status": "done", "updated_at": "2026-11-18T10:00:01Z", "deleted_at": "2026-11-18T10:00:02Z"},
        ],
        "edges": [{"task_id": "task-b", "depends_on_id": "task-a"}],
        "cutoff": cutoff, "task_count": 2, "edge_count": 1,
        "consistent_snapshot": True, "local_rust_sync": False, "automatic_apply": False,
    }


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.manifest = self.root / "manifest.bin"
        self.journal = self.root / "pull.sqlite3"
        self.canonical = self.root / "tasks.sqlite3"
        self.canonical.write_bytes(b"CANONICAL TASK DATA - DO NOT TOUCH")
        self._make_journal()

    def _make_journal(self, sample=None):
        sample = sample or baseline()
        db = sqlite3.connect(self.journal)
        db.executescript("""
            CREATE TABLE pull_state(workspace_id TEXT PRIMARY KEY,cursor INTEGER,cutoff INTEGER,baseline_required INTEGER);
            CREATE TABLE pull_events(seq INTEGER PRIMARY KEY,kind TEXT,task_id TEXT,depends_on_id TEXT,task_version INTEGER,occurred_at TEXT);
            CREATE TABLE pull_baseline_meta(workspace_id TEXT PRIMARY KEY,cutoff INTEGER,task_count INTEGER,edge_count INTEGER,sha256 TEXT);
            CREATE TABLE pull_baseline_tasks(id TEXT PRIMARY KEY,version INTEGER,status TEXT,updated_at TEXT,deleted_at TEXT);
            CREATE TABLE pull_baseline_edges(task_id TEXT,depends_on_id TEXT,PRIMARY KEY(task_id,depends_on_id));
            PRAGMA user_version=2;
        """)
        digest = hashlib.sha256(json.dumps(sample, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        db.execute("INSERT INTO pull_state VALUES(?,?,?,?)", ("personal", sample["cutoff"], None, 1))
        db.execute("INSERT INTO pull_baseline_meta VALUES(?,?,?,?,?)", ("personal", sample["cutoff"], sample["task_count"], sample["edge_count"], digest))
        db.executemany("INSERT INTO pull_baseline_tasks VALUES(?,?,?,?,?)", [tuple(x[k] for k in ("id", "version", "status", "updated_at", "deleted_at")) for x in sample["items"]])
        db.executemany("INSERT INTO pull_baseline_edges VALUES(?,?)", [(x["task_id"], x["depends_on_id"]) for x in sample["edges"]])
        db.commit()
        db.close()
        os.chmod(self.journal, 0o600)

    def _local(self, rows):
        self.manifest.write_bytes(manifest(rows))
        os.chmod(self.manifest, 0o600)
        return review.local_manifest(review.private_file_bytes(self.manifest, review.MAX_LOCAL_BYTES))

    def test_counts_are_metadata_only_and_provenance_always_unverified(self):
        loc, edges = self._local([
            ("task-a", "2", "todo", "2026-11-18T09:00:00Z", "", ""),
            ("task-c", "1", "todo", "2026-11-18T09:00:00Z", "", "task-a"),
        ])
        remote, redges, cutoff, checkpoint, changes, unfinished = review.baseline_journal(self.journal)
        report = review.compare(loc, edges, remote, redges, cutoff, checkpoint, changes, unfinished)
        self.assertEqual((report["local_only_ids"], report["remote_only_baseline_ids"], report["shared_ids_provenance_unverified"]), (1, 1, 1))
        self.assertEqual(report["local_only_dependency_edges"], 1)
        self.assertEqual(report["remote_only_baseline_dependency_edges"], 1)
        self.assertTrue(report["identity_review_required"])
        self.assertFalse(report["safe_to_apply"])
        self.assertFalse(report["data_transfer_performed"])
        self.assertEqual(self.canonical.read_bytes(), b"CANONICAL TASK DATA - DO NOT TOUCH")

    def test_delete_vs_edit_is_flagged_without_resolving(self):
        local, edges = self._local([
            ("task-a", "3", "todo", "2026-11-18T09:00:00Z", "2026-11-18T09:01:00Z", ""),
            ("task-b", "4", "done", "2026-11-18T09:00:00Z", "", ""),
        ])
        remote, links, *rest = review.baseline_journal(self.journal)
        out = review.compare(local, edges, remote, links, *rest)
        self.assertEqual(out["shared_ids_revision_disagreement"], 2)
        self.assertEqual(out["delete_vs_active_disagreement"], 2)

    def test_post_baseline_events_mark_remote_snapshot_stale(self):
        db = sqlite3.connect(self.journal)
        db.execute("INSERT INTO pull_events VALUES(8,'task.update','task-a',NULL,3,'2026-11-18T11:00:00Z')")
        db.execute("UPDATE pull_state SET cursor=8,cutoff=10")
        db.commit()
        db.close()
        remote, links, *rest = review.baseline_journal(self.journal)
        out = review.compare({}, set(), remote, links, *rest)
        self.assertEqual(out["post_baseline_remote_events"], 1)
        self.assertTrue(out["unfinished_remote_event_page"])
        self.assertTrue(out["baseline_is_not_current_remote_when_deltas_exist"])

    def test_corrupt_baseline_digest_fails_closed(self):
        db = sqlite3.connect(self.journal)
        db.execute("UPDATE pull_baseline_tasks SET version=88 WHERE id='task-a'")
        db.commit()
        db.close()
        with self.assertRaisesRegex(review.ReviewError, "digest mismatch"):
            review.baseline_journal(self.journal)

    def test_rejects_non_private_and_symlinked_input(self):
        self.manifest.write_bytes(manifest([]))
        os.chmod(self.manifest, 0o644)
        with self.assertRaisesRegex(review.ReviewError, "private"):
            review.private_file_bytes(self.manifest, 4_000_000)
        os.chmod(self.manifest, 0o600)
        link = self.root / "alias"
        link.symlink_to(self.manifest)
        with self.assertRaises(OSError):
            review.private_file_bytes(link, 4_000_000)

    def test_rejects_bad_frame_duplicate_and_body_export(self):
        with self.assertRaisesRegex(review.ReviewError, "Expected binary"):
            review.local_manifest(b"SHIORI-BRIDGE-2\n")
        with self.assertRaisesRegex(review.ReviewError, "Truncated"):
            review.local_manifest(review.MARKER + b"\x00\x00\x00\x07hi")
        row = ("task-a", "2", "todo", "2026-11-18T09:00:00Z", "", "")
        with self.assertRaisesRegex(review.ReviewError, "Unordered"):
            review.local_manifest(manifest([row, row]))

    def test_rejects_unstaged_v1_and_unsafe_checkpoint(self):
        db = sqlite3.connect(self.journal)
        db.execute("PRAGMA user_version=1")
        db.commit()
        db.close()
        with self.assertRaisesRegex(review.ReviewError, "v2"):
            review.baseline_journal(self.journal)
        db = sqlite3.connect(self.journal)
        db.execute("PRAGMA user_version=2")
        db.execute("UPDATE pull_state SET cursor=1")
        db.commit()
        db.close()
        with self.assertRaisesRegex(review.ReviewError, "untrusted"):
            review.baseline_journal(self.journal)


    def test_delta_impact_summarizes_affected_identities_without_exposing_them(self):
        local, links = self._local([
            ("task-a", "2", "todo", "2026-11-18T09:00:00Z", "", ""),
            ("task-c", "1", "todo", "2026-11-18T09:00:00Z", "", ""),
            ("task-d", "1", "todo", "2026-11-18T09:00:00Z", "", ""),
        ])
        db = sqlite3.connect(self.journal)
        db.executemany(
            "INSERT INTO pull_events VALUES(?,?,?,?,?,?)",
            [(8, "task.update", "task-a", None, 3, "2026-11-18T11:01:00Z"),
             (9, "task.delete", "task-a", None, 4, "2026-11-18T11:02:00Z"),
             (10, "task.insert", "task-c", None, 1, "2026-11-18T11:03:00Z"),
             (11, "edge.add", "task-c", "task-a", None, "2026-11-18T11:04:00Z"),
             (12, "edge.remove", "task-b", "task-a", None, "2026-11-18T11:05:00Z")],
        )
        db.execute("UPDATE pull_state SET cursor=12,cutoff=NULL")
        db.commit()
        db.close()
        remote, edges, cutoff, checkpoint, count, incomplete, impact = review.baseline_journal(
            self.journal, include_delta=True)
        report = review.compare(local, links, remote, edges, cutoff, checkpoint, count,
                                incomplete, impact)
        self.assertEqual(report["remote_delta_insert_events"], 1)
        self.assertEqual(report["remote_delta_update_events"], 1)
        self.assertEqual(report["remote_delta_delete_events"], 1)
        self.assertEqual(report["remote_delta_purge_events"], 0)
        self.assertEqual(report["remote_delta_dependency_events"], 2)
        self.assertEqual(report["remote_delta_distinct_changed_task_ids"], 2)
        self.assertEqual(report["remote_delta_distinct_changed_dependency_pairs"], 2)
        self.assertEqual(report["remote_delta_changed_shared_ids"], 1)
        self.assertEqual(report["remote_delta_changed_local_only_ids"], 1)
        self.assertEqual(report["remote_delta_changed_ids_absent_from_baseline"], 1)
        self.assertEqual(report["remote_delta_possible_delete_vs_local_active"], 1)
        self.assertEqual(report["remote_delta_versions_ahead_of_baseline"], 1)
        self.assertEqual(report["remote_delta_dependency_endpoints_absent_from_baseline"], 1)
        self.assertEqual(report["remote_delta_dependency_endpoints_absent_locally"], 1)
        self.assertTrue(report["identity_review_required"])
        self.assertFalse(report["safe_to_apply"])
        output = json.dumps(report)
        for secret in ("task-a", "task-b", "task-c", "task-d", "2026-11-18T11:"):
            self.assertNotIn(secret, output)
        self.assertEqual(self.canonical.read_bytes(), b"CANONICAL TASK DATA - DO NOT TOUCH")

    def test_delta_impact_does_not_infer_provenance_from_clean_metadata(self):
        local, links = self._local([
            ("task-a", "2", "todo", "2026-11-18T09:00:00Z", "", ""),
            ("task-b", "3", "done", "2026-11-18T09:00:00Z",
             "2026-11-18T09:01:00Z", ""),
        ])
        remote, edges, cutoff, checkpoint, count, incomplete, impact = review.baseline_journal(
            self.journal, include_delta=True)
        report = review.compare(local, links, remote, edges, cutoff, checkpoint, count,
                                incomplete, impact)
        self.assertEqual(report["post_baseline_remote_events"], 0)
        self.assertEqual(report["remote_delta_distinct_changed_task_ids"], 0)
        self.assertEqual(report["remote_delta_dependency_events"], 0)
        self.assertEqual(report["shared_ids_provenance_unverified"], 2)
        self.assertFalse(report["safe_to_apply"])

    def test_delta_impact_refuses_an_event_beyond_checkpoint(self):
        db = sqlite3.connect(self.journal)
        db.execute("INSERT INTO pull_events VALUES(8,'task.update','task-a',NULL,3,'2026-11-18T11:00:00Z')")
        db.commit()
        db.close()
        with self.assertRaisesRegex(review.ReviewError, "uncheckpointed"):
            review.baseline_journal(self.journal, include_delta=True)

    def test_delta_impact_refuses_unrecognized_or_malformed_events(self):
        db = sqlite3.connect(self.journal)
        db.execute("INSERT INTO pull_events VALUES(8,'unexpected','task-a',NULL,3,'2026-11-18T11:00:00Z')")
        db.execute("UPDATE pull_state SET cursor=8")
        db.commit()
        db.close()
        with self.assertRaisesRegex(review.ReviewError, "Malformed"):
            review.baseline_journal(self.journal, include_delta=True)
        db = sqlite3.connect(self.journal)
        db.execute("UPDATE pull_events SET kind='edge.add',depends_on_id='task-a',task_version=3 WHERE seq=8")
        db.commit()
        db.close()
        with self.assertRaisesRegex(review.ReviewError, "Malformed"):
            review.baseline_journal(self.journal, include_delta=True)

if __name__ == "__main__":
    unittest.main()
