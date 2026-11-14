"""Safety contracts for the M2.8 emulator-only upgrade rehearsal (no actual ADB)."""
import copy
import json
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import call, patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools" / "android"))
import rehearse_emulator_upgrade as rehearsal  # noqa: E402


PREVIOUS = {
    "version_code": 5, "git_commit": "a" * 40,
    "signer_certificate_sha256": "c" * 64,
}
CANDIDATE = {
    "version_code": 6, "git_commit": "b" * 40,
    "signer_certificate_sha256": "c" * 64,
}
SERIAL = "emulator-5554"


class UpgradeRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = pathlib.Path(self.folder.name)
        self.args = SimpleNamespace(
            serial=SERIAL,
            previous_apk=root / "previous.apk",
            candidate_apk=root / "candidate.apk",
            state_file=root / "stage.json",
            report=root / "report.json",
            confirm_synthetic_data=True,
        )
        self.before = {name: None for name in (*rehearsal.PROTECTED, rehearsal.RECOVERY)}
        self.before[rehearsal.PROTECTED[0]] = {
            "bytes": 100, "sha256": "d" * 64,
        }

    def state(self):
        return {
            "format": rehearsal.FORMAT,
            "serial": SERIAL,
            "previous_apk_sha256": "f" * 64,
            "candidate_apk_sha256": "f" * 64,
            "previous_commit": PREVIOUS["git_commit"],
            "candidate_commit": CANDIDATE["git_commit"],
            "signer_certificate_sha256": PREVIOUS["signer_certificate_sha256"],
            "previous_version_code": 5,
            "candidate_version_code": 6,
            "physical_device_acceptance": "not-verified",
            "release_ready": False,
        }

    def test_refuses_real_device_and_bad_emulator_identity(self):
        with patch.object(rehearsal, "adb") as adb:
            with self.assertRaisesRegex(RuntimeError, "serial"):
                rehearsal.require_fresh_emulator("R58M1234")
            adb.assert_not_called()
            adb.side_effect = ["List of devices attached\nemulator-5554\tdevice\n", "0\n"]
            with self.assertRaisesRegex(RuntimeError, "not verified"):
                rehearsal.require_fresh_emulator(SERIAL)

    def test_refuses_multiple_devices_including_a_connected_phone(self):
        with patch.object(rehearsal, "adb", return_value=(
            "List of devices attached\nemulator-5554\tdevice\n"
            "R58M1234\tdevice\n"
        )):
            with self.assertRaisesRegex(RuntimeError, "Exactly one"):
                rehearsal.require_fresh_emulator(SERIAL)

    def test_refuses_existing_app_before_baseline_install(self):
        with patch.object(rehearsal, "require_fresh_emulator"), patch.object(
            rehearsal, "installed_version", return_value=5
        ), patch.object(rehearsal, "adb") as adb:
            with self.assertRaisesRegex(RuntimeError, "already installed"):
                rehearsal.stage(self.args, PREVIOUS, CANDIDATE)
            adb.assert_not_called()

    def test_baseline_installs_only_to_new_emulator_and_writes_provenance(self):
        with patch.object(rehearsal, "require_fresh_emulator"), patch.object(
            rehearsal, "installed_version", side_effect=[None, 5]
        ), patch.object(rehearsal, "adb", return_value="Success\n") as adb, patch.object(
            rehearsal, "sha256_file", return_value="f" * 64
        ):
            rehearsal.stage(self.args, PREVIOUS, CANDIDATE)
        self.assertEqual(json.loads(self.args.state_file.read_text()), self.state())
        self.assertTrue(any(x.args[:3] == ("-s", SERIAL, "install") for x in adb.call_args_list))
        self.assertFalse(any("uninstall" in x.args for x in adb.call_args_list))
        self.assertNotIn("task", json.dumps(self.state()).lower())
        with patch.object(rehearsal, "adb") as adb:
            with self.assertRaisesRegex(RuntimeError, "Stage file already exists"):
                rehearsal.stage(self.args, PREVIOUS, CANDIDATE)
            adb.assert_not_called()

    def test_refuses_stale_apk_manifest_without_touching_emulator(self):
        state = self.state()
        state["candidate_apk_sha256"] = "0" * 64
        self.args.state_file.write_text(json.dumps(state))
        with patch.object(rehearsal, "sha256_file", return_value="f" * 64), patch.object(
            rehearsal, "adb"
        ) as adb:
            with self.assertRaisesRegex(RuntimeError, "provenance changed"):
                rehearsal.upgrade(self.args, PREVIOUS, CANDIDATE)
            adb.assert_not_called()

    def test_no_upgrade_without_explicit_synthetic_data_confirmation(self):
        self.args.confirm_synthetic_data = False
        with patch.object(rehearsal, "adb") as adb:
            with self.assertRaisesRegex(RuntimeError, "confirm-synthetic-data"):
                rehearsal.upgrade(self.args, PREVIOUS, CANDIDATE)
            adb.assert_not_called()

    def test_in_place_upgrade_inspects_data_and_never_uninstalls(self):
        self.args.state_file.write_text(json.dumps(self.state()))
        with patch.object(rehearsal, "sha256_file", return_value="f" * 64), patch.object(
            rehearsal, "require_fresh_emulator"
        ), patch.object(rehearsal, "installed_version", side_effect=[5, 6]), patch.object(
            rehearsal, "private_metadata", side_effect=[self.before, copy.deepcopy(self.before)]
        ), patch.object(rehearsal, "webview_size", side_effect=[4, 5]), patch.object(
            rehearsal, "adb", return_value="Success\n"
        ) as adb:
            rehearsal.upgrade(self.args, PREVIOUS, CANDIDATE)
        report = json.loads(self.args.report.read_text())
        self.assertEqual(report["format"], rehearsal.REPORT_FORMAT)
        self.assertEqual(report["manual_task_parity"], "pending")
        self.assertFalse(report["release_ready"])
        self.assertEqual(report["physical_device_acceptance"], "not-verified")
        self.assertEqual(report["missing_private_files"], [])
        self.assertTrue(any(x.args[:4] == ("-s", SERIAL, "install", "-r")
                            for x in adb.call_args_list))
        self.assertFalse(any("uninstall" in x.args for x in adb.call_args_list))
        self.assertNotIn("task title", self.args.report.read_text().lower())

    def test_missing_private_storage_blocks_approval_and_preserves_report(self):
        self.args.state_file.write_text(json.dumps(self.state()))
        after = copy.deepcopy(self.before)
        after[rehearsal.PROTECTED[0]] = None
        with patch.object(rehearsal, "sha256_file", return_value="f" * 64), patch.object(
            rehearsal, "require_fresh_emulator"
        ), patch.object(rehearsal, "installed_version", side_effect=[5, 6]), patch.object(
            rehearsal, "private_metadata", side_effect=[self.before, after]
        ), patch.object(rehearsal, "webview_size", side_effect=[4, 4]), patch.object(
            rehearsal, "adb", return_value="Success\n"
        ):
            with self.assertRaisesRegex(RuntimeError, "storage vanished"):
                rehearsal.upgrade(self.args, PREVIOUS, CANDIDATE)
        report = json.loads(self.args.report.read_text())
        self.assertEqual(report["missing_private_files"], [rehearsal.PROTECTED[0]])

    def test_strict_private_metadata_parser_blocks_duplicates(self):
        line = f"{rehearsal.PROTECTED[0]}|10|{'a' * 64}\n"
        with patch.object(rehearsal, "adb", return_value=line + line):
            with self.assertRaisesRegex(RuntimeError, "duplicated"):
                rehearsal.private_metadata(SERIAL)

    def test_cli_requires_explicit_disposable_emulator_opt_in(self):
        with self.assertRaises(SystemExit) as ctx:
            rehearsal.main(["stage", "--serial", SERIAL,
                            "--previous-apk", "a.apk",
                            "--previous-evidence", "a.json",
                            "--candidate-apk", "b.apk",
                            "--candidate-evidence", "b.json",
                            "--state-file", "stage.json"])
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
