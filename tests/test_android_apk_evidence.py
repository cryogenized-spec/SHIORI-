"""Offline contract tests for APK evidence (no SDK or Android device required)."""
import importlib.util
import json
import pathlib
import tempfile
import unittest
import zipfile
from unittest.mock import patch

MODULE = pathlib.Path(__file__).resolve().parents[1] / "tools" / "android" / "apk_release_evidence.py"
spec = importlib.util.spec_from_file_location("shiori_apk_evidence", MODULE)
evidence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evidence)

SHA = "a" * 40
SIGNATURE = "b" * 64


class AndroidEvidenceContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = pathlib.Path(self.temp.name)
        self.apk = self.base / "app-debug.apk"
        self.manifest = self.base / "evidence.json"
        self.write_apk()

    def write_apk(self, overrides=None):
        contents = {
            name: (b"android-local offline" if name == "assets/app.js"
                   else f"embedded {name}".encode("utf-8"))
            for name in evidence.REQUIRED
        }
        if overrides:
            contents.update(overrides)
        with zipfile.ZipFile(self.apk, "w", compression=zipfile.ZIP_DEFLATED) as out:
            for name, data in contents.items():
                if data is not None:
                    out.writestr(name, data)

    @staticmethod
    def fake_sdk(*args):
        if "badging" in args:
            return "package: name='dev.cryogenized.shiori' versionCode='5' versionName='0.1.4-dev'\n"
        if "permissions" in args:
            return "package: dev.cryogenized.shiori\n"
        if "verify" in args:
            return "Verifies\nSigner #1 certificate SHA-256 digest: " + SIGNATURE + "\n"
        raise AssertionError(f"unexpected Android command: {args}")

    def test_exact_debug_artifact_can_be_created_and_verified(self):
        with patch.object(evidence, "command", side_effect=self.fake_sdk):
            record = evidence.create(self.apk, SHA, "aapt", "apksigner")
        self.assertEqual(record["format"], evidence.FORMAT)
        self.assertIs(record["release_ready"], False)
        self.assertEqual(record["physical_device_acceptance"], "not-verified")
        self.assertEqual(set(record["resources"]), set(evidence.REQUIRED))
        self.manifest.write_text(json.dumps(record))
        self.assertEqual(evidence.verify(self.apk, self.manifest, SHA), record)

    def test_rejects_tampered_apk_and_unexpected_commit(self):
        with patch.object(evidence, "command", side_effect=self.fake_sdk):
            record = evidence.create(self.apk, SHA, "aapt", "apksigner")
        self.manifest.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "another commit"):
            evidence.verify(self.apk, self.manifest, "c" * 40)
        self.write_apk({"assets/styles.css": b"changed stylesheet"})
        with self.assertRaisesRegex(ValueError, "downloaded APK bytes"):
            evidence.verify(self.apk, self.manifest, SHA)

    def test_refuses_missing_or_empty_native_resource(self):
        self.write_apk({"lib/x86_64/libshiori_android_native.so": None})
        with self.assertRaisesRegex(ValueError, "missing required"):
            evidence.inspect(self.apk)
        self.write_apk({"lib/x86_64/libshiori_android_native.so": b""})
        with self.assertRaisesRegex(ValueError, "empty resource"):
            evidence.inspect(self.apk)

    def test_refuses_permissions_or_non_dev_versions(self):
        def permission_sdk(*args):
            result = self.fake_sdk(*args)
            if "permissions" in args:
                result += "uses-permission: name='android.permission.INTERNET'\n"
            return result
        with patch.object(evidence, "command", side_effect=permission_sdk):
            with self.assertRaisesRegex(ValueError, "requests Android permissions"):
                evidence.create(self.apk, SHA, "aapt", "apksigner")

        def release_sdk(*args):
            result = self.fake_sdk(*args)
            if "badging" in args:
                return result.replace("0.1.4-dev", "0.1.4")
            return result
        with patch.object(evidence, "command", side_effect=release_sdk):
            with self.assertRaisesRegex(ValueError, "dev/debug"):
                evidence.create(self.apk, SHA, "aapt", "apksigner")

    def test_refuses_forged_acceptance_and_duplicate_zip_members(self):
        with patch.object(evidence, "command", side_effect=self.fake_sdk):
            record = evidence.create(self.apk, SHA, "aapt", "apksigner")
        record["physical_device_acceptance"] = "passed"
        self.manifest.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, "incomplete"):
            evidence.verify(self.apk, self.manifest, SHA)
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(self.apk, "a") as out:
                out.writestr("assets/app.js", b"android-local duplicate")
        with self.assertRaisesRegex(ValueError, "duplicate paths"):
            evidence.inspect(self.apk)


if __name__ == "__main__":
    unittest.main()
