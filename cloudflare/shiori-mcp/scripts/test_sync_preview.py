import unittest
import struct
from sync_preview import compare, fingerprint, decode_manifest, compare_manifest


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

if __name__=="__main__":
    unittest.main()
