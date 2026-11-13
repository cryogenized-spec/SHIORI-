"""Offline CI for the privacy-preserving ADB device recovery harness.

These are mock-interface tests. They do NOT claim to have run on a phone.
"""
import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "android" / "verify_recovery_device.py"
spec = importlib.util.spec_from_file_location("shiori_recovery_device", MODULE)
device = importlib.util.module_from_spec(spec)
spec.loader.exec_module(device)


class RecoveryDeviceContract(unittest.TestCase):
    def test_device_inspection_uses_run_as_and_hashes_only(self):
        stdout = "\n".join(
            f"{name}|{128 if name == device.RECOVERY else 64}|{'a'*64}"
            for name in (*device.PROTECTED, device.RECOVERY)
        )
        calls = []
        def fake_adb(args):
            calls.append(args)
            return "device" if args == ["get-state"] else stdout

        with patch.object(device, "adb", side_effect=fake_adb):
            result = device.state()
        self.assertEqual(len(result), len(device.PROTECTED) + 1)
        self.assertEqual(result[device.RECOVERY]["bytes"], 128)
        self.assertEqual(calls[0], ["get-state"])
        self.assertEqual(calls[1][:3], ["shell", "run-as", device.APP_ID])
        self.assertNotIn("rm ", " ".join(calls[1]))
        self.assertNotIn("cat ", " ".join(calls[1]))

    def test_covers_selected_primary_rollback_vault_and_sqlite_sidecars(self):
        self.assertIn("shiori-native-primary-canary-v1.sqlite3", device.PROTECTED)
        self.assertIn("shiori-legacy-cutover-rollback-v1.sqlite3", device.PROTECTED)
        self.assertIn("shiori-native-cutover-candidate-v1.sqlite3", device.PROTECTED)
        for name in device.DATABASES:
            for suffix in ("-wal", "-shm", "-journal"):
                self.assertIn(name + suffix, device.PROTECTED)

    def test_rejects_duplicate_rows_and_invalid_hex_digest(self):
        rows = "\\n".join(
            f"{name}|100|{'a' * 64}" for name in (*device.PROTECTED, device.RECOVERY)
        )
        for forged in (
            rows + "\\n" + f"{device.PROTECTED[0]}|100|{'a' * 64}",
            rows.replace("a" * 64, "z" * 64, 1),
        ):
            def fake_adb(args):
                return "device" if args == ["get-state"] else forged
            with patch.object(device, "adb", side_effect=fake_adb):
                with self.assertRaises(RuntimeError):
                    device.state()

    def test_refuses_missing_recovery_or_unexpected_rows(self):
        def fake_adb(args):
            if args == ["get-state"]:
                return "device"
            return "unexpected.sqlite3|100|" + "a" * 64
        with patch.object(device, "adb", side_effect=fake_adb):
            with self.assertRaisesRegex(RuntimeError, "Unexpected ADB"):
                device.state()

    def test_snapshot_manifest_contains_digests_not_task_contents(self):
        with tempfile.TemporaryDirectory() as temp:
            baseline = pathlib.Path(temp) / "baseline.json"
            files = {name: {"bytes": 10, "sha256": "a" * 64} for name in device.PROTECTED}
            files[device.RECOVERY] = None
            with patch.object(device, "state", return_value=files):
                with patch.object(sys, "argv", ["verify_recovery_device.py", "snapshot",
                                              "--output", str(baseline)]):
                    self.assertEqual(device.main(), 0)
            self.assertNotIn("title", baseline.read_text())
            self.assertNotIn("notes", baseline.read_text())
            result = dict(files)
            result[device.RECOVERY] = {"bytes": 8192, "sha256": "b" * 64}
            with patch.object(device, "state", return_value=result):
                with patch.object(sys, "argv", ["verify_recovery_device.py", "verify",
                                              "--baseline", str(baseline)]):
                    self.assertEqual(device.main(), 0)
            # The old three-database harness missed active-primary and
            # sidecar modifications. Both now fail closed.
            result["shiori-native-primary-canary-v1.sqlite3"] = {
                "bytes": 11, "sha256": "c" * 64
            }
            with patch.object(device, "state", return_value=result):
                with patch.object(sys, "argv", ["verify_recovery_device.py", "verify",
                                              "--baseline", str(baseline)]):
                    self.assertEqual(device.main(), 1)
            result["shiori-native-primary-canary-v1.sqlite3"] = None
            result["shiori-native-working-v1.sqlite3-wal"] = {
                "bytes": 44, "sha256": "d" * 64
            }
            with patch.object(device, "state", return_value=result):
                with patch.object(sys, "argv", ["verify_recovery_device.py", "verify",
                                              "--baseline", str(baseline)]):
                    self.assertEqual(device.main(), 1)
            result["shiori-native-working-v1.sqlite3-wal"] = None
            result[device.PROTECTED[0]] = {"bytes": 11, "sha256": "c" * 64}
            with patch.object(device, "state", return_value=result):
                with patch.object(sys, "argv", ["verify_recovery_device.py", "verify",
                                              "--baseline", str(baseline)]):
                    self.assertEqual(device.main(), 1)


if __name__ == "__main__":
    unittest.main()
