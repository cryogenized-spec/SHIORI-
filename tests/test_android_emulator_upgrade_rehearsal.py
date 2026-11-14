"""Safety contracts for the M2.8 emulator-only upgrade rehearsal (no actual ADB)."""
import copy
import json
import os
import pathlib
import shlex
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
BOOT_ID = "11111111-2222-3333-4444-555555555555"
TRIAL_MARKER = ".shiori-m2-8-trial-" + "e" * 32
REAL_READINESS = rehearsal.wait_for_app_readiness


class UpgradeRehearsalTests(unittest.TestCase):
    def setUp(self):
        for target, attr, value in (
            (rehearsal, "emulator_boot_id", BOOT_ID),
            (rehearsal, "verify_trial_marker", None),
            (rehearsal, "wait_for_app_readiness", None),
            (rehearsal.secrets, "token_hex", "e" * 32),
        ):
            fake = patch.object(target, attr)
            mock = fake.start()
            if value is not None:
                mock.return_value = value
            self.addCleanup(fake.stop)
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
            "emulator_boot_id": BOOT_ID,
            "trial_marker": TRIAL_MARKER,
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
        self.assertEqual(os.stat(self.args.state_file).st_mode & 0o777, 0o600)
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


    def test_android_pm_absent_status_one_does_not_hide_transport_errors(self):
        with patch.object(rehearsal.subprocess, "run", return_value=SimpleNamespace(
            returncode=1, stdout="", stderr=""
        )) as runner:
            self.assertIsNone(rehearsal.installed_version(SERIAL))
            self.assertEqual(runner.call_args.args[0][-3:], ["pm", "path", rehearsal.APP_ID])
        with patch.object(rehearsal.subprocess, "run", return_value=SimpleNamespace(
            returncode=1, stdout="", stderr="device offline"
        )):
            with self.assertRaisesRegex(RuntimeError, "package-manager query failed"):
                rehearsal.installed_version(SERIAL)

    def test_remote_metadata_script_is_one_shell_argument(self):
        calls = []
        def capture(*args, **kwargs):
            calls.append(args)
            if args[3:5] == ("run-as", rehearsal.APP_ID) and "sha256sum" in args[-1]:
                return "".join(name + "|absent|absent\n"
                               for name in (*rehearsal.PROTECTED, rehearsal.RECOVERY))
            return "absent\n"
        with patch.object(rehearsal, "adb", side_effect=capture):
            rehearsal.private_metadata(SERIAL)
            rehearsal.webview_size(SERIAL)
        self.assertEqual(len(calls), 2)
        for args in calls:
            parsed = shlex.split(" ".join(args[3:]))
            self.assertEqual(parsed[:4], ["run-as", rehearsal.APP_ID, "sh", "-c"])
            self.assertEqual(len(parsed), 5)
            self.assertIn("if [", parsed[4])

    def test_different_emulator_boot_with_same_serial_blocks_upgrade(self):
        self.args.state_file.write_text(json.dumps(self.state()))
        with patch.object(rehearsal, "sha256_file", return_value="f" * 64), patch.object(
            rehearsal, "require_fresh_emulator"
        ), patch.object(rehearsal, "emulator_boot_id",
            return_value="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        ), patch.object(rehearsal, "adb") as adb:
            with self.assertRaisesRegex(RuntimeError, "replaced or restarted"):
                rehearsal.upgrade(self.args, PREVIOUS, CANDIDATE)
            adb.assert_not_called()

    def test_missing_private_trial_marker_blocks_upgrade_before_mutation(self):
        self.args.state_file.write_text(json.dumps(self.state()))
        with patch.object(rehearsal, "sha256_file", return_value="f" * 64), patch.object(
            rehearsal, "require_fresh_emulator"
        ), patch.object(rehearsal, "installed_version", return_value=5
        ), patch.object(rehearsal, "verify_trial_marker",
            side_effect=RuntimeError("Staged emulator trial marker is missing")
        ), patch.object(rehearsal, "adb") as adb:
            with self.assertRaisesRegex(RuntimeError, "trial marker is missing"):
                rehearsal.upgrade(self.args, PREVIOUS, CANDIDATE)
            adb.assert_not_called()


    def test_launch_timeout_retains_baseline_hashes_before_upgrade(self):
        self.args.state_file.write_text(json.dumps(self.state()))
        def inject(*command, **kwargs):
            if command[2:5] == ("shell", "am", "start"):
                raise RuntimeError("synthetic launch timeout")
            return "Success\n"
        with patch.object(rehearsal, "sha256_file", return_value="f" * 64), patch.object(
            rehearsal, "require_fresh_emulator"
        ), patch.object(rehearsal, "installed_version", side_effect=[5, 6]), patch.object(
            rehearsal, "private_metadata", return_value=self.before
        ), patch.object(rehearsal, "webview_size", return_value=4), patch.object(
            rehearsal, "adb", side_effect=inject
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic launch timeout"):
                rehearsal.upgrade(self.args, PREVIOUS, CANDIDATE)
        report = json.loads(self.args.report.read_text())
        self.assertEqual(report["baseline_private_hashes"], self.before)
        self.assertEqual(report["phase"], "launching-candidate")
        self.assertEqual(report["status"], "incomplete")
        self.assertIsNone(report["candidate_private_hashes"])

    def test_failed_post_upgrade_snapshot_preserves_original_evidence(self):
        self.args.state_file.write_text(json.dumps(self.state()))
        with patch.object(rehearsal, "sha256_file", return_value="f" * 64), patch.object(
            rehearsal, "require_fresh_emulator"
        ), patch.object(rehearsal, "installed_version", side_effect=[5, 6]), patch.object(
            rehearsal, "private_metadata", side_effect=[
                self.before, RuntimeError("synthetic post-snapshot error")
            ]
        ), patch.object(rehearsal, "webview_size", return_value=4), patch.object(
            rehearsal, "adb", return_value="Success\n"
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic post-snapshot error"):
                rehearsal.upgrade(self.args, PREVIOUS, CANDIDATE)
        report = json.loads(self.args.report.read_text())
        self.assertEqual(report["baseline_private_hashes"], self.before)
        self.assertEqual(report["phase"], "capturing-post-upgrade-metadata")
        self.assertEqual(report["status"], "incomplete")

    def test_delayed_readiness_succeeds_only_after_repeated_stable_observations(self):
        counter = [0]
        def tick():
            counter[0] += 1
            return counter[0]
        def probe(*command, **kwargs):
            if "pidof" in command:
                return "123\n"
            return "mCurrentFocus=Window{abc dev.cryogenized.shiori/.MainActivity}\n"
        with patch.object(rehearsal, "adb", side_effect=probe), patch.object(
            rehearsal, "webview_size", side_effect=[None, 4, 4, 4]
        ), patch.object(rehearsal, "private_metadata", return_value=self.before
        ), patch.object(rehearsal.time, "monotonic", side_effect=tick), patch.object(
            rehearsal.time, "sleep"
        ) as sleep:
            REAL_READINESS(SERIAL, timeout_s=8, poll_interval_s=0)
            self.assertGreaterEqual(sleep.call_count, 3)

    def test_unready_or_crashed_app_times_out_without_reporting_success(self):
        counter = [0]
        def tick():
            counter[0] += 1
            return counter[0]
        with patch.object(rehearsal, "adb", return_value=""), patch.object(
            rehearsal, "webview_size", return_value=4
        ), patch.object(rehearsal, "private_metadata", return_value=self.before
        ), patch.object(rehearsal.time, "monotonic", side_effect=tick), patch.object(
            rehearsal.time, "sleep"
        ):
            with self.assertRaisesRegex(RuntimeError, "did not reach stable"):
                REAL_READINESS(SERIAL, timeout_s=3, poll_interval_s=0)

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
