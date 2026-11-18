"""S3 metadata-only remote pull journal: no network, no canonical task writes."""
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"cloudflare/shiori-mcp/scripts"))
import sync_pull_journal as pull


def event(seq: int, kind: str = "task.update", task_id: str = "test-task-id"):
    return {"seq": seq, "kind": kind, "task_id": task_id, "depends_on_id": None,
            "task_version": seq, "occurred_at": "2026-11-18T14:00:00Z"}


def page(events, cutoff, next_cursor=None):
    return {"changes":events,"cutoff":cutoff,
            "checkpoint_cursor":(events[-1]["seq"] if events else 0) if next_cursor is not None else cutoff,
            "next_cursor":next_cursor,"baseline_required":True,"local_rust_sync":False}


def baseline_sample(cutoff=7):
    return {"items":[
        {"id":"task-a","version":2,"status":"todo",
         "updated_at":"2026-11-18T08:00:00Z","deleted_at":None},
        {"id":"task-b","version":3,"status":"done",
         "updated_at":"2026-11-18T08:02:00Z",
         "deleted_at":"2026-11-18T08:03:00Z"}],
        "edges":[{"task_id":"task-b","depends_on_id":"task-a"}],
        "cutoff":cutoff,"task_count":2,"edge_count":1,
        "consistent_snapshot":True,"local_rust_sync":False,"automatic_apply":False}


class PullJournalTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        self.file=self.root/"tasks.pull.sqlite3"
        self.canonical=self.root/"tasks.sqlite3"
        self.canonical.write_bytes(b"CANONICAL USER DATA IS OFF LIMITS")
        self.journal=pull.init_journal(self.file)
        self.addCleanup(self.journal.close)

    def test_created_private_only_for_purpose_and_preserves_primary(self):
        self.assertEqual(self.file.stat().st_mode & 0o077,0)
        self.assertEqual(pull.state(self.journal),(0,None,True,0))
        self.assertEqual(self.canonical.read_bytes(),b"CANONICAL USER DATA IS OFF LIMITS")
        self.assertEqual(self.journal.execute("PRAGMA user_version").fetchone()[0],2)

    def test_one_read_only_poll_persists_changelog_without_applying_tasks(self):
        feed=page([event(1,"task.insert"),event(2)],2)
        with patch.object(pull,"request_page",return_value=feed) as requester:
            self.assertEqual(pull.poll(self.journal,"fake-owner-token",5),(2,2,None))
            requester.assert_called_once_with("fake-owner-token",0,None)
        self.assertEqual(pull.state(self.journal),(2,None,True,2))
        self.assertEqual([x[0] for x in self.journal.execute("SELECT seq FROM pull_events ORDER BY seq")],[1,2])
        self.assertEqual(self.canonical.read_bytes(),b"CANONICAL USER DATA IS OFF LIMITS")

    def test_crash_after_first_page_recovers_same_cutoff_and_cursor(self):
        first=page([event(1),event(3)],5,3)
        invalid=page([event(2)],5)
        with patch.object(pull,"request_page",side_effect=[first,invalid]):
            with self.assertRaisesRegex(pull.PullError,"increasing"):
                pull.poll(self.journal,"fake",5)
        self.assertEqual(pull.state(self.journal),(3,5,True,2))
        self.journal.close()
        self.journal=pull.init_journal(self.file)
        next_page=page([event(5)],5)
        with patch.object(pull,"request_page",return_value=next_page) as spy:
            self.assertEqual(pull.poll(self.journal,"fake",5),(1,5,None))
            spy.assert_called_once_with("fake",3,5)
        self.assertEqual(pull.state(self.journal),(5,None,True,3))

    def test_rejects_unexpected_task_content_or_false_guarantees(self):
        bad=page([event(1)],1)
        bad["changes"][0]["notes"]="SECRET DO NOT DOWNLOAD"
        with self.assertRaisesRegex(pull.PullError,"Unexpected event"):
            pull.check_page(bad,0,None)
        self.assertEqual(pull.state(self.journal),(0,None,True,0))
        fake=page([],0)
        fake["baseline_required"]=False
        with self.assertRaisesRegex(pull.PullError,"unsupported"):
            pull.check_page(fake,0,None)
        fake=page([],0)
        fake["local_rust_sync"]=True
        with self.assertRaisesRegex(pull.PullError,"unsupported"):
            pull.check_page(fake,0,None)

    def test_rejects_regressing_cutoff_changed_cutoff_and_duplicate_sequence(self):
        with self.assertRaisesRegex(pull.PullError,"cutoff"):
            pull.check_page(page([],3),4,None)
        with self.assertRaisesRegex(pull.PullError,"cutoff"):
            pull.check_page(page([],4),0,5)
        with self.assertRaisesRegex(pull.PullError,"increasing"):
            pull.check_page(page([event(1),event(1)],2),0,None)
        with self.assertRaisesRegex(pull.PullError,"continuation"):
            pull.check_page(page([],2,1),0,None)

    def test_foreign_workspace_gaps_do_not_require_sequence_contiguity(self):
        changes=[event(4,"task.insert"),event(9,"task.delete")]
        first=page(changes,12)
        with patch.object(pull,"request_page",return_value=first):
            self.assertEqual(pull.poll(self.journal,"fake",5),(2,12,None))
        self.assertEqual([r[0] for r in self.journal.execute("SELECT seq FROM pull_events")],[4,9])

    def test_dependency_events_have_different_minimal_shape(self):
        edge=event(1,"edge.add")
        edge["depends_on_id"]="other-task"
        edge["task_version"]=None
        valid=pull.check_page(page([edge],1),0,None)
        self.assertEqual(valid[0][0]["depends_on_id"],"other-task")
        edge["notes"]="not allowed"
        with self.assertRaises(pull.PullError):
            pull.check_page(page([edge],1),0,None)

    def test_concurrent_checkpoint_change_never_inserts_event(self):
        with self.assertRaisesRegex(pull.PullError,"Another receiver"):
            pull.persist_page(self.journal,[event(1)],2,None,2,2,None)
        self.assertEqual(pull.state(self.journal),(0,None,True,0))

    def test_refuses_symlink_world_readable_and_existing_canonical_database(self):
        link=self.root/"linked"
        link.symlink_to(self.file)
        with self.assertRaisesRegex(pull.PullError,"private"):
            pull.init_journal(link)
        os.chmod(self.file,0o644)
        with self.assertRaisesRegex(pull.PullError,"private"):
            pull.init_journal(self.file)
        os.chmod(self.file,0o600)
        with self.assertRaises(pull.PullError):
            pull.init_journal(self.canonical)
        alias=self.root/"existing-native.db"
        con=sqlite3.connect(alias)
        con.execute("CREATE TABLE tasks (id TEXT)")
        con.close()
        os.chmod(alias,0o600)
        with self.assertRaisesRegex(pull.PullError,"existing database"):
            pull.init_journal(alias)

    def test_no_network_for_status_and_private_token_only(self):
        token=self.root/"token"
        token.write_text("not-an-oauth-approval-code")
        os.chmod(token,0o644)
        with self.assertRaisesRegex(pull.PullError,"private"):
            pull.token_from_file(token)
        os.chmod(token,0o600)
        self.assertEqual(pull.token_from_file(token),"not-an-oauth-approval-code")
        with patch.object(pull,"urlopen") as opener:
            self.assertEqual(pull.state(self.journal),(0,None,True,0))
            opener.assert_not_called()


    def test_atomic_baseline_sets_first_delta_cursor_without_importing_tasks(self):
        snapshot=baseline_sample(7)
        self.assertEqual(pull.persist_baseline(self.journal,snapshot),7)
        self.assertEqual(pull.state(self.journal),(7,None,True,0))
        self.assertEqual(pull.baseline_info(self.journal),(7,2,1))
        self.assertEqual(self.journal.execute("SELECT COUNT(*) FROM pull_baseline_tasks").fetchone()[0],2)
        self.assertEqual(self.journal.execute("SELECT COUNT(*) FROM pull_baseline_edges").fetchone()[0],1)
        self.assertEqual(self.canonical.read_bytes(),b"CANONICAL USER DATA IS OFF LIMITS")
        self.journal.close()
        self.journal=pull.init_journal(self.file)
        self.assertEqual(pull.baseline_info(self.journal),(7,2,1))
        delta=page([event(8,"task.update","task-a")],8)
        with patch.object(pull,"request_page",return_value=delta) as spy:
            self.assertEqual(pull.poll(self.journal,"fake",5),(1,8,None))
            spy.assert_called_once_with("fake",7,None)
        self.assertEqual(pull.state(self.journal),(8,None,True,1))
        self.assertEqual(self.canonical.read_bytes(),b"CANONICAL USER DATA IS OFF LIMITS")
        with self.assertRaisesRegex(pull.PullError,"fresh, empty"):
            pull.persist_baseline(self.journal,snapshot)

    def test_bad_baseline_content_and_dangling_edges_are_rejected_before_checkpoint(self):
        import copy
        original=baseline_sample(12)
        cases=[
            ({"notes":"SENSITIVE TASK CONTENT"},"Unknown baseline fields"),
            ({"consistent_snapshot":False},"unsupported"),
            ({"automatic_apply":True},"unsupported"),
            ({"task_count":3},"Incomplete"),
        ]
        for changes,error in cases:
            payload=copy.deepcopy(original)
            payload.update(changes)
            with self.subTest(changes=changes):
                with self.assertRaisesRegex(pull.PullError,error):
                    pull.persist_baseline(self.journal,payload)
                self.assertEqual(pull.state(self.journal),(0,None,True,0))
        badly_ordered=copy.deepcopy(original)
        badly_ordered["items"].reverse()
        with self.assertRaisesRegex(pull.PullError,"Unordered"):
            pull.persist_baseline(self.journal,badly_ordered)
        broken_edge=copy.deepcopy(original)
        broken_edge["edges"][0]["depends_on_id"]="unknown"
        with self.assertRaisesRegex(pull.PullError,"Dangling"):
            pull.persist_baseline(self.journal,broken_edge)
        dangerous=copy.deepcopy(original)
        dangerous["items"][0]["body"]="NO CUSTOMER CONTENT"
        with self.assertRaisesRegex(pull.PullError,"Unexpected baseline task fields"):
            pull.persist_baseline(self.journal,dangerous)
        self.assertEqual(self.journal.execute("SELECT COUNT(*) FROM pull_baseline_meta").fetchone()[0],0)

    def test_existing_receiver_history_requires_fresh_journal_for_baseline(self):
        with patch.object(pull,"request_page",return_value=page([event(1)],1)):
            self.assertEqual(pull.poll(self.journal,"token",1),(1,1,None))
        with self.assertRaisesRegex(pull.PullError,"fresh, empty"):
            pull.persist_baseline(self.journal,baseline_sample())
        self.assertEqual(pull.state(self.journal),(1,None,True,1))
        self.assertEqual(self.journal.execute("SELECT COUNT(*) FROM pull_baseline_meta").fetchone()[0],0)

    def test_schema_v1_upgrade_preserves_metadata_events_and_checkpoint(self):
        old_file=self.root/"old-pull-v1.sqlite3"
        con=sqlite3.connect(old_file)
        con.executescript("""
        CREATE TABLE pull_state(workspace_id TEXT PRIMARY KEY,cursor INTEGER,
          cutoff INTEGER,baseline_required INTEGER);
        CREATE TABLE pull_events(seq INTEGER PRIMARY KEY,kind TEXT,task_id TEXT,
          depends_on_id TEXT,task_version INTEGER,occurred_at TEXT);
        INSERT INTO pull_state VALUES('personal',3,NULL,1);
        INSERT INTO pull_events VALUES(3,'task.update','test-old',NULL,2,'2026-11-18T00:00:00Z');
        PRAGMA user_version=1;
        """)
        con.close()
        os.chmod(old_file,0o600)
        upgraded=pull.init_journal(old_file)
        try:
            self.assertEqual(upgraded.execute("PRAGMA user_version").fetchone()[0],2)
            self.assertEqual(pull.state(upgraded),(3,None,True,1))
            self.assertIsNone(pull.baseline_info(upgraded))
            with self.assertRaisesRegex(pull.PullError,"fresh, empty"):
                pull.persist_baseline(upgraded,baseline_sample())
        finally:
            upgraded.close()

    def test_remote_baseline_request_is_metadata_only_and_token_private(self):
        seen=[]
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self,*args): return None
            def read(self,size=-1):
                return json.dumps({"ok":True,"operation_id":"sync.baseline.read",
                                   "data":baseline_sample()}).encode()
        def network(req,timeout):
            seen.append(req)
            return FakeResponse()
        with patch.object(pull,"urlopen",side_effect=network):
            result=pull.request_baseline("synthetic-private-token")
        self.assertEqual(result["cutoff"],7)
        self.assertEqual(len(seen),1)
        self.assertEqual(json.loads(seen[0].data),{"workspace_id":"personal"})
        self.assertEqual(seen[0].get_method(),"POST")
        self.assertTrue(seen[0].full_url.endswith("sync.baseline.read"))
        self.assertEqual(seen[0].get_header("Authorization"),"Bearer synthetic-private-token")


    def test_request_only_sends_cursor_and_owner_workspace(self):
        reqs=[]
        class FakeResponse:
            def __enter__(self):return self
            def __exit__(self,*args):return None
            def read(self, size=-1):
                return json.dumps({"ok":True,"operation_id":"sync.changes.read",
                                   "data":page([],7)}).encode()
        def network(req,timeout):
            reqs.append(req)
            return FakeResponse()
        with patch.object(pull,"urlopen",side_effect=network):
            result=pull.request_page("test-token",4,7)
        self.assertEqual(result["cutoff"],7)
        self.assertEqual(len(reqs),1)
        request_body=json.loads(reqs[0].data)
        self.assertEqual(request_body,{"workspace_id":"personal","cursor":4,"limit":100,"cutoff":7})
        self.assertNotIn("notes",str(request_body))

if __name__=="__main__":
    unittest.main()
