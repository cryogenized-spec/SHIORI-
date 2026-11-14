"""Offline unit tests for a non-installing Android upgrade identity preflight."""
import copy
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools" / "android"))
import compare_debug_upgrades as upgrade  # noqa: E402
from compare_debug_upgrades import compare_records  # noqa: E402


def evidence(commit, code=5, signer="c" * 64):
    return {
        "format": "shiori-android-debug-evidence-v1",
        "package": "dev.cryogenized.shiori",
        "artifact_kind": "debug-alpha-not-for-publication",
        "release_ready": False,
        "physical_device_acceptance": "not-verified",
        "network_permission": False,
        "git_commit": commit,
        "version_code": code,
        "version_name": "0.1.4-dev",
        "signer_certificate_sha256": signer,
    }


class DebugUpgradePreflightTests(unittest.TestCase):
    def setUp(self):
        self.previous = evidence("a" * 40)
        self.candidate = evidence("b" * 40, code=6)

    def test_accepts_distinct_evidenced_builds_same_signer_higher_code(self):
        self.assertIn("NOT handset upgrade approval",
                      compare_records(self.previous, self.candidate))

    def test_verifies_manifest_metadata_against_actual_apk(self):
        record = copy.deepcopy(self.previous)
        with patch.object(upgrade, "verify") as checksum, patch.object(
            upgrade, "create", return_value=record
        ) as direct:
            upgrade.verify_against_apk(
                pathlib.Path("previous.apk"), pathlib.Path("evidence.json"),
                record, "aapt", "apksigner"
            )
            checksum.assert_called_once()
            direct.assert_called_once()

        forged = copy.deepcopy(record)
        forged["signer_certificate_sha256"] = "d" * 64
        with patch.object(upgrade, "verify"), patch.object(
            upgrade, "create", return_value=record
        ):
            with self.assertRaisesRegex(ValueError, "independently inspected"):
                upgrade.verify_against_apk(
                    pathlib.Path("forged.apk"), pathlib.Path("forged.json"),
                    forged, "aapt", "apksigner"
                )

    def test_rejects_forged_version_and_permissions_in_evidence(self):
        actual = copy.deepcopy(self.candidate)
        for field, value in (
            ("version_code", 999),
            ("version_name", "100.0-dev"),
            ("network_permission", True),
        ):
            with self.subTest(field=field):
                forged = copy.deepcopy(actual)
                forged[field] = value
                with patch.object(upgrade, "verify"), patch.object(
                    upgrade, "create", return_value=actual
                ):
                    with self.assertRaisesRegex(ValueError, "independently inspected"):
                        upgrade.verify_against_apk(
                            pathlib.Path("app.apk"), pathlib.Path("evidence.json"),
                            forged, "aapt", "apksigner"
                        )

    def test_rejects_different_signer(self):
        self.candidate["signer_certificate_sha256"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "signing certificate changed"):
            compare_records(self.previous, self.candidate)

    def test_rejects_same_version_and_downgrade(self):
        for code in (5, 4):
            with self.subTest(version_code=code):
                self.candidate["version_code"] = code
                with self.assertRaisesRegex(ValueError, "versionCode must increase"):
                    compare_records(self.previous, self.candidate)

    def test_rejects_same_commit(self):
        self.candidate["git_commit"] = "a" * 40
        with self.assertRaisesRegex(ValueError, "distinct source revision"):
            compare_records(self.previous, self.candidate)

    def test_rejects_false_phone_approval_and_release_flag(self):
        for field, value in (("physical_device_acceptance", "passed"),
                             ("release_ready", True),
                             ("artifact_kind", "production"),
                             ("network_permission", True)):
            with self.subTest(field=field):
                bad = copy.deepcopy(self.candidate)
                bad[field] = value
                with self.assertRaisesRegex(ValueError, "not an approved offline debug"):
                    compare_records(self.previous, bad)

    def test_rejects_wrong_package_or_manifest_format(self):
        for field, value in (("package", "org.other.app"),
                             ("format", "unknown")):
            with self.subTest(field=field):
                bad = copy.deepcopy(self.candidate)
                bad[field] = value
                with self.assertRaises(ValueError):
                    compare_records(self.previous, bad)

    def test_rejects_non_integer_version_and_invalid_hashes(self):
        for bad_value in (True, "6", 0, -1):
            with self.subTest(value=bad_value):
                bad = copy.deepcopy(self.candidate)
                bad["version_code"] = bad_value
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    compare_records(self.previous, bad)
        self.candidate["signer_certificate_sha256"] = "NOT-A-DIGEST"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            compare_records(self.previous, self.candidate)
        self.candidate["signer_certificate_sha256"] = "c" * 64
        self.candidate["git_commit"] = "not-a-commit"
        with self.assertRaisesRegex(ValueError, "commit identifier"):
            compare_records(self.previous, self.candidate)

    def test_rejects_missing_or_malformed_record(self):
        for record in (None, [], {}, {"package": "dev.cryogenized.shiori"}):
            with self.subTest(record=record):
                with self.assertRaises(ValueError):
                    compare_records(self.previous, record)


if __name__ == "__main__":
    unittest.main()
