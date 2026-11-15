import unittest
from sync_preview import compare, fingerprint


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


if __name__=="__main__":
    unittest.main()
