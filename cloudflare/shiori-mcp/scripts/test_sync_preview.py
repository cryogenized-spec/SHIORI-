import unittest
import struct
import io
import json
from unittest.mock import patch
from sync_preview import (
    compare, fingerprint, decode_manifest, compare_manifest, load_remote_manifest,
    remote_manifest_request,
)


class SyncPreviewTests(unittest.TestCase):
    def test_empty_is_safe_and_read_only(self):
        result=compare([],[])
        self.assertEqual(result["mode"],"read_only_no_writes")
        self.assertEqual(result["counts"]["local_total"],0)
        self.assertEqual(result["counts"]["remote_total"],0)

    def test_same_ids_detect_changes(self):
        local=[{"id":"a","title":"Inspection","status":"todo","project":"Rig"}]
        remote=[{"id":"a","title":"Inspection","status":"done","project":"Rig"}]
        result=compare(local,remote)["counts"]
        self.assertEqual(result["same_id"],1)
        self.assertEqual(result["same_id_changed"],1)

    def test_same_titles_are_only_suggestions_not_identity(self):
        local=[{"id":"local-123","title":"  Inspection  ","status":"todo","project":"Rig"}]
        remote=[{"id":"remote-456","title":"inspection","status":"done","project":"rig"}]
        result=compare(local,remote)["counts"]
        self.assertEqual(result["same_id"],0)
        self.assertEqual(result["local_only"],1)
        self.assertEqual(result["remote_only"],1)
        self.assertEqual(result["possible_title_matches_not_authoritative"],1)
        self.assertEqual(fingerprint(local[0]),fingerprint(remote[0]))

    def test_legacy_preview_rejects_duplicate_active_ids_without_leaking_content(self):
        sample={"id":"private-id","title":"Confidential task",
                "status":"todo","project":"Private"}
        for source in ("local","remote"):
            with self.subTest(source=source):
                local=[sample,sample.copy()] if source=="local" else []
                remote=[sample,sample.copy()] if source=="remote" else []
                with self.assertRaisesRegex(ValueError, f"Duplicate {source} task identities") as ctx:
                    compare(local,remote)
                self.assertNotIn("private-id",str(ctx.exception))
                self.assertNotIn("Confidential",str(ctx.exception))

    def test_no_data_contents_leak_into_report(self):
        local=[{"id":"private-id","title":"Private customer information","status":"todo","project":"Secret"}]
        result=compare(local,[])
        text=str(result)
        self.assertNotIn("Private customer",text)
        self.assertNotIn("private-id",text)



class NativeManifestTests(unittest.TestCase):
    @staticmethod
    def encode(*rows):
        out = bytearray(b"SHIORI-MANIFEST-1\n")
        for row in rows:
            for value in row:
                blob = value.encode("utf-8")
                out.extend(struct.pack(">I", len(blob)))
                out.extend(blob)
        return bytes(out)

    def test_revisions_edges_and_tombstones_have_no_task_content(self):
        data = self.encode(
            ("task-a","3","done","2026-11-17T12:00:00Z","",""),
            ("task-b","5","todo","2026-11-17T13:00:00Z","","task-a"),
            ("task-c","4","todo","2026-11-17T14:00:00Z","2026-11-17T15:00:00Z",""),
        )
        local = decode_manifest(data)
        self.assertEqual(len(local),3)
        self.assertTrue(local[2]["deleted"])
        self.assertEqual(local[1]["depends_on"],["task-a"])
        report=compare_manifest(local,[{"id":"task-a","version":2},{"id":"cloud-only","version":1}])
        self.assertEqual(report["mode"],"s1_read_only_manifest_no_sync")
        self.assertEqual(report["counts"]["local_tombstones"],1)
        self.assertEqual(report["counts"]["local_dependency_edges"],1)
        self.assertEqual(report["counts"]["matching_id_revision_differences"],1)
        self.assertEqual(report["counts"]["local_active_only"],1)
        self.assertEqual(report["counts"]["remote_active_only"],1)
        self.assertNotIn("task-a",str(report))
        self.assertNotIn("task-b",str(report))

    def test_rejects_bad_manifest(self):
        valid=self.encode(("a","1","todo","now","",""))
        cases=(b"",b"wrong",valid[:-1],
               self.encode(("a","1","todo","now","","a")),
               self.encode(("a","0","todo","now","","")),
               self.encode(("a","1","garbage","now","","")),
               self.encode(("a","1","todo","now","",""),("a","1","todo","now","","")))
        for data in cases:
            with self.subTest(data=data[:30]):
                with self.assertRaises(ValueError):
                    decode_manifest(data)

class RemoteManifestTests(unittest.TestCase):
    def test_paged_private_manifest_uses_only_read_operations(self):
        seen = []
        def fake_urlopen(request, timeout):
            self.assertEqual(request.get_method(), "POST")
            self.assertTrue(request.full_url.endswith("/api/v1/ops/sync.manifest.read"))
            payload=json.loads(request.data)
            self.assertEqual(set(payload), {"workspace_id","limit"} if len(seen)==0 else {"workspace_id","limit","cursor"})
            self.assertEqual(payload["workspace_id"],"personal")
            self.assertEqual(payload["limit"],100)
            self.assertNotIn("Secret customer",str(payload))
            seen.append(payload)
            sample={"id":"native-a","version":3,"status":"todo",
                    "updated_at":"2026-11-18T05:00:00Z","deleted_at":None}
            data={"ok":True,"operation_id":"sync.manifest.read","data":{
                "items":[sample] if len(seen)==1 else [],
                "next_cursor":"native-a" if len(seen)==1 else None,
                "consistent_snapshot":False,"local_rust_sync":False}}
            return io.BytesIO(json.dumps(data).encode("utf-8"))
        with patch("sync_preview.urlopen",side_effect=fake_urlopen):
            remote=load_remote_manifest("https://example.invalid","fake-private-token")
        self.assertEqual(len(remote),1)
        self.assertEqual(len(seen),2)
        self.assertEqual(seen[1]["cursor"],"native-a")

    def test_remote_manifest_refuses_task_content_or_false_sync_claims(self):
        bad={"ok":True,"operation_id":"sync.manifest.read","data":{
            "items":[{"id":"a","version":1,"status":"todo",
                      "updated_at":"now","deleted_at":None,"notes":"SHOULD NOT BE HERE"}],
            "next_cursor":None,"consistent_snapshot":False,"local_rust_sync":False}}
        with patch("sync_preview.urlopen",return_value=io.BytesIO(json.dumps(bad).encode())):
            with self.assertRaises(ValueError):
                remote_manifest_request("https://example.invalid","private",None)
        bad["data"]["items"]=[]
        bad["data"]["local_rust_sync"]=True
        with patch("sync_preview.urlopen",return_value=io.BytesIO(json.dumps(bad).encode())):
            with self.assertRaises(ValueError):
                remote_manifest_request("https://example.invalid","private",None)

    def test_duplicate_manifest_identifiers_fail_closed_without_leaking_ids(self):
        local=[{"id":"private-local-id","version":1,"deleted":False,"depends_on":[]}]
        remote=[{"id":"private-remote-id","version":1,"deleted_at":None}]
        for left,right,expected in (
            (local * 2, remote, "Duplicate local task identities"),
            (local, remote * 2, "Duplicate remote task identities"),
            (local + [{"id":"private-local-id","version":2,"deleted":True,"depends_on":[]}],
             remote, "Duplicate local task identities"),
            (local, remote + [{"id":"private-remote-id","version":2,"deleted_at":"now"}],
             "Duplicate remote task identities"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected) as error:
                    compare_manifest(left,right)
                self.assertNotIn("private-local-id",str(error.exception))
                self.assertNotIn("private-remote-id",str(error.exception))
        self.assertEqual(compare_manifest(local,remote)["counts"]["local_active_only"],1)

    def test_tombstone_conflicts_are_counted_without_leaking_identifiers(self):
        local=[
            {"id":"x","version":4,"deleted":True,"depends_on":[]},
            {"id":"y","version":2,"deleted":False,"depends_on":[]},
            {"id":"z","version":2,"deleted":False,"depends_on":[]},
        ]
        remote=[
            {"id":"x","version":2,"deleted_at":None},
            {"id":"y","version":3,"deleted_at":"2026-11-18T05:00:00Z"},
            {"id":"z","version":2,"deleted_at":None},
        ]
        report=compare_manifest(local,remote)
        self.assertEqual(report["counts"]["local_deleted_remote_active"],1)
        self.assertEqual(report["counts"]["local_active_remote_deleted"],1)
        self.assertEqual(report["counts"]["remote_tombstones"],1)
        self.assertNotIn("'x'",str(report))
        self.assertNotIn("'y'",str(report))

if __name__=="__main__":
    unittest.main()
