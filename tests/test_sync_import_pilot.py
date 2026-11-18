"""No-network contract tests for the explicit S2 Rust outbox import pilot."""
import argparse
import hashlib
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
import sync_import_pilot as pilot

DEVICE="22222222-2222-4222-8222-222222222222"
TASK="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PROPOSAL="99999999-9999-4999-8999-999999999999"
RECEIPT="88888888-8888-4888-8888-888888888888"
EVENT=f"sync1:{DEVICE}:{TASK}:1"


def fixture(directory:Path,depends_on=None,revision=1):
    journal=directory/"tasks.sync.sqlite3"
    canonical=directory/"tasks.sqlite3"
    token=directory/"owner-token"
    payload=json.dumps({
        "schema_version":1,"event_id":EVENT,"origin_device_id":DEVICE,
        "workspace_id":"personal","task":{
            "id":TASK,"title":"PRIVATE PROJECT TITLE","notes":"SECRET CUSTOMER PRIVATE NOTE",
            "project":"DEMO","priority":"medium","status":"todo",
            "due_on":"2026-11-20","estimate_minutes":45,"assignee_id":"local",
            "created_at":"2026-11-18T07:00:00Z","updated_at":"2026-11-18T07:00:00Z",
            "completed_at":None,"version":revision,"deleted_at":None,
        },"depends_on":[] if depends_on is None else depends_on,
    },separators=(",",":"))
    con=sqlite3.connect(journal)
    con.executescript("""
    PRAGMA user_version=1;
    CREATE TABLE sync_meta(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE sync_outbox(event_id TEXT PRIMARY KEY,task_id TEXT,local_version INTEGER,
                             payload_json TEXT,state TEXT);
    """)
    con.execute("INSERT INTO sync_meta VALUES('device_id',?)",(DEVICE,))
    con.execute("INSERT INTO sync_outbox VALUES(?,?,?,?,?)",(EVENT,TASK,revision,payload,"pending"))
    con.commit();con.close()
    original=sqlite3.connect(canonical)
    original.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, version INTEGER NOT NULL, deleted_at TEXT)")
    original.execute("INSERT INTO tasks VALUES(?,?,NULL)",(TASK,revision))
    original.commit();original.close()
    token.write_text("SYNTHETIC_TEST_BEARER_ONLY",encoding="utf8")
    os.chmod(journal,0o600);os.chmod(token,0o600)
    return journal,canonical,token,payload


def arguments(command,journal,canonical,token,**kwargs):
    return argparse.Namespace(
        action=command,journal=journal,database=canonical,token_file=token,
        cli=Path("target/debug/shiori-cli"),event_id=EVENT,
        confirm_pairing=False,confirm_import=False,proposal_id=PROPOSAL,
        **kwargs
    )


class ImportPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.journal,self.canonical,self.token,self.payload=fixture(self.folder)
        self.digest=hashlib.sha256(self.payload.encode()).hexdigest()

    def opts(self,cmd):
        return arguments(cmd,self.journal,self.canonical,self.token)

    def test_pair_requires_explicit_owner_approval(self):
        with patch.object(pilot,"api_call") as api:
            with self.assertRaisesRegex(pilot.SyncPilotError,"confirm-pairing"):
                pilot.run(self.opts("pair"))
            api.assert_not_called()
        opts=self.opts("pair");opts.confirm_pairing=True
        with patch.object(pilot,"api_call",return_value={"device_id":DEVICE}) as api:
            self.assertEqual(pilot.run(opts),0)
        self.assertEqual(api.call_args.args[0],"sync.device.pair")
        self.assertTrue(api.call_args.args[2]["confirm_pairing"])

    def test_preview_sends_no_task_content(self):
        with patch.object(pilot,"api_call",return_value={
            "proposal_id":PROPOSAL,"task_id":TASK,"local_version":1,"expires_at":"2026-11-18T07:15:00Z"
        }) as api:
            self.assertEqual(pilot.run(self.opts("preview")),0)
        operation,token,args=api.call_args.args
        self.assertEqual(operation,"sync.import.preview")
        self.assertEqual(args["payload_sha256"],self.digest)
        self.assertEqual(args["event_id"],EVENT)
        self.assertNotIn("PRIVATE",str(args))
        self.assertNotIn("SECRET",str(args))
        self.assertNotIn("payload_json",args)

    def test_apply_requires_explicit_consent_before_any_upload(self):
        with patch.object(pilot,"api_call") as api:
            with self.assertRaisesRegex(pilot.SyncPilotError,"confirm-import"):
                pilot.run(self.opts("apply"))
            api.assert_not_called()

    def test_apply_checks_receipt_before_acknowledging_canonical_event(self):
        opts=self.opts("apply");opts.confirm_import=True
        receipt={"receipt_id":RECEIPT,"resource_id":TASK,"source_event_id":EVENT,
                 "source_version":1,"remote_revision":1,
                 "source_payload_sha256":self.digest,"remote_modified":False}
        def remote(op,token,args):
            if op=="sync.import.apply":
                self.assertEqual(args["payload_json"],self.payload)
                self.assertTrue(args["owner_approved"])
                self.assertEqual(args["idempotency_key"],"s2apply-"+PROPOSAL)
                return {"resource_id":TASK,"revision":1,
                        "source_event_id":EVENT,"source_payload_sha256":self.digest}
            if op=="sync.import.receipt.read":
                self.assertEqual(args["event_id"],EVENT)
                return receipt
            self.fail("Unexpected operation "+op)
        with patch.object(pilot,"api_call",side_effect=remote) as api,patch.object(
            pilot,"acknowledge_local",return_value="Acknowledged verified remote receipt"
        ) as acknowledge:
            self.assertEqual(pilot.run(opts),0)
        self.assertEqual([call.args[0] for call in api.call_args_list],
                         ["sync.import.apply","sync.import.receipt.read"])
        self.assertEqual(acknowledge.call_args.args[3],EVENT)
        self.assertEqual(acknowledge.call_args.args[4],TASK)

    def test_divergent_remote_revision_never_acknowledges(self):
        opts=self.opts("apply");opts.confirm_import=True
        def remote(op,token,args):
            if op=="sync.import.apply":
                return {"resource_id":TASK,"revision":1,"source_event_id":EVENT,
                        "source_payload_sha256":self.digest}
            return {"receipt_id":RECEIPT,"resource_id":TASK,"source_event_id":EVENT,
                    "source_version":1,"remote_revision":2,
                    "source_payload_sha256":self.digest,"remote_modified":True}
        with patch.object(pilot,"api_call",side_effect=remote),patch.object(
            pilot,"acknowledge_local"
        ) as ack:
            with self.assertRaisesRegex(pilot.SyncPilotError,"inconsistent"):
                pilot.run(opts)
            ack.assert_not_called()

    def test_rejects_modified_synthetic_payload_before_any_transfer(self):
        con=sqlite3.connect(self.journal)
        obj=json.loads(self.payload)
        obj["depends_on"]=["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"]
        con.execute("UPDATE sync_outbox SET payload_json=?",(json.dumps(obj),))
        con.commit();con.close()
        with patch.object(pilot,"api_call") as api:
            with self.assertRaisesRegex(pilot.SyncPilotError,"unsupported"):
                pilot.run(self.opts("preview"))
            api.assert_not_called()

    def test_private_files_required_and_no_accidental_creation(self):
        os.chmod(self.token,0o644)
        with self.assertRaisesRegex(pilot.SyncPilotError,"non-private"):
            pilot.read_token(self.token)
        os.chmod(self.token,0o600)
        link=self.folder/"linked-journal.db"
        link.symlink_to(self.journal)
        with self.assertRaisesRegex(pilot.SyncPilotError,"non-private"):
            pilot.journal_state(link)
        missing=self.folder/"missing.db"
        with self.assertRaises(OSError):
            pilot.journal_state(missing)
        self.assertFalse(missing.exists())

    def test_changed_canonical_revision_stops_preview_and_apply_before_network(self):
        with sqlite3.connect(self.canonical) as con:
            con.execute("UPDATE tasks SET version=2 WHERE id=?",(TASK,))
        for action in ("preview","apply"):
            opts=self.opts(action)
            if action=="apply": opts.confirm_import=True
            with patch.object(pilot,"api_call") as api:
                with self.assertRaisesRegex(pilot.SyncPilotError,"changed since staging"):
                    pilot.run(opts)
                api.assert_not_called()

    def test_unexpected_local_version_and_tombstones_fail_closed(self):
        with sqlite3.connect(self.journal) as con:
            con.execute("UPDATE sync_outbox SET local_version=2")
        device,db=pilot.journal_state(self.journal)
        try:
            with self.assertRaisesRegex(pilot.SyncPilotError,"revision 1"):
                pilot.pending_event(db,device,EVENT)
        finally:
            db.close()


if __name__=="__main__":
    unittest.main()
