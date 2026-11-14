#!/usr/bin/env python3
"""Create/verify a self-contained SHIORI Android *debug* APK evidence record.

No file is uploaded from an Android phone. The evidence contains hashes,
package metadata and signer-public-certificate digest only, never private keys
or user task data. This script is NOT a release signer or publication gate.
"""
import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import zipfile

PACKAGE = "dev.cryogenized.shiori"
ABIS = ("armeabi-v7a", "arm64-v8a", "x86_64")
ASSETS = (
    "assets/index.html",
    "assets/app.js",
    "assets/styles.css",
    "assets/assets/shiori-muse.webp",
)
REQUIRED = ASSETS + tuple(
    f"lib/{abi}/libshiori_android_native.so" for abi in ABIS
)
FORMAT = "shiori-android-debug-evidence-v1"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def command(*args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=35, check=False)
    if result.returncode:
        raise RuntimeError(f"Android SDK tool failed: {args[0]}: {result.stderr[:320]}")
    return result.stdout


def inspect(apk):
    if not apk.is_file() or apk.stat().st_size <= 0:
        raise ValueError("missing or empty debug APK")
    with zipfile.ZipFile(apk) as archive:
        if archive.testzip() is not None:
            raise ValueError("APK has a corrupt ZIP entry")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("APK ZIP contains duplicate paths")
        missing = set(REQUIRED) - set(names)
        if missing:
            raise ValueError(f"APK is missing required offline resources: {sorted(missing)}")
        hashes = {}
        for name in REQUIRED:
            content = archive.read(name)
            if not content:
                raise ValueError(f"APK contains an empty resource: {name}")
            hashes[name] = {"bytes": len(content), "sha256": sha256(content)}
        if b"android-local" not in archive.read("assets/app.js"):
            raise ValueError("packaged UI is not the Android-local edition")
    return hashes


def create(apk, commit, aapt, apksigner):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit must be the full lowercase git SHA")
    resources = inspect(apk)
    badging = command(aapt, "dump", "badging", str(apk))
    package = re.search(
        r"^package: name='([^']+)' versionCode='([^']+)' versionName='([^']+)'",
        badging, re.MULTILINE
    )
    if not package or package.group(1) != PACKAGE:
        raise ValueError("unexpected Android package ID")
    version_code, version_name = package.group(2), package.group(3)
    if not version_code.isdigit() or not version_name.endswith("-dev"):
        raise ValueError("this acceptance gate only supports dev/debug APKs")
    permissions = command(aapt, "dump", "permissions", str(apk))
    if re.search(r"android\.permission\.[A-Za-z0-9_.]+", permissions):
        raise ValueError("debug alpha unexpectedly requests Android permissions")
    certificates = command(apksigner, "verify", "--print-certs", str(apk))
    signer = re.search(
        r"Signer #1 certificate SHA-256 digest: ([0-9a-fA-F]{64})",
        certificates,
    )
    if not signer:
        raise ValueError("Android APK signer verification lacks a certificate SHA-256")
    return {
        "format": FORMAT, "release_ready": False,
        "artifact_kind": "debug-alpha-not-for-publication",
        "physical_device_acceptance": "not-verified",
        "git_commit": commit,
        "package": PACKAGE, "version_code": int(version_code),
        "version_name": version_name,
        "apk": {"name": apk.name, "bytes": apk.stat().st_size,
                "sha256": sha256(apk.read_bytes())},
        "signer_certificate_sha256": signer.group(1).lower(),
        "resources": resources,
        "network_permission": False,
    }


def verify(apk, manifest, commit):
    record = json.loads(manifest.read_text(encoding="utf-8"))
    if (record.get("format") != FORMAT or
        record.get("artifact_kind") != "debug-alpha-not-for-publication" or
        record.get("release_ready") is not False or
        record.get("physical_device_acceptance") != "not-verified" or
        record.get("git_commit") != commit or
        record.get("package") != PACKAGE or
        record.get("network_permission") is not False):
        raise ValueError("APK evidence record is incomplete or from another commit")
    expected = record.get("apk")
    if (not isinstance(expected, dict) or
        expected.get("name") != apk.name or
        expected.get("bytes") != apk.stat().st_size or
        expected.get("sha256") != sha256(apk.read_bytes())):
        raise ValueError("downloaded APK bytes do not match the CI evidence manifest")
    if record.get("resources") != inspect(apk):
        raise ValueError("packaged asset/JNI hashes do not match the evidence manifest")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create_cmd = sub.add_parser("create")
    create_cmd.add_argument("--apk", required=True, type=pathlib.Path)
    create_cmd.add_argument("--output", required=True, type=pathlib.Path)
    create_cmd.add_argument("--commit", required=True)
    create_cmd.add_argument("--aapt", required=True)
    create_cmd.add_argument("--apksigner", required=True)
    verify_cmd = sub.add_parser("verify")
    verify_cmd.add_argument("--apk", required=True, type=pathlib.Path)
    verify_cmd.add_argument("--manifest", required=True, type=pathlib.Path)
    verify_cmd.add_argument("--commit", required=True)
    args = parser.parse_args()
    try:
        if args.action == "create":
            # Do not overwrite an existing evidence record from another build.
            record = create(args.apk, args.commit, args.aapt, args.apksigner)
            with args.output.open("x", encoding="utf-8") as out:
                json.dump(record, out, indent=2, sort_keys=True)
                out.write("\n")
            print("PASS: Android debug APK evidence created; physical acceptance remains blocked")
        else:
            verify(args.apk, args.manifest, args.commit)
            print("PASS: downloaded APK exactly matches its commit-bound evidence manifest")
    except (ValueError, OSError, KeyError, json.JSONDecodeError,
            zipfile.BadZipFile, subprocess.TimeoutExpired, RuntimeError) as err:
        print(f"FAILED SHIORI Android evidence gate: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
