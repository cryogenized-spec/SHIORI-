#!/usr/bin/env python3
"""Read-only preflight for two SHIORI CI debug APKs, never a device install.

Both APKs must match their commit-bound evidence manifests. This checks
package identity, public signing fingerprint and increasing versionCode
before anyone attempts an in-place upgrade on a DISPOSABLE Android profile.
It does not verify that the OS accepts the upgrade or preserve any real data.
"""
import argparse
import json
import pathlib
import re
import sys
import zipfile

from apk_release_evidence import FORMAT, PACKAGE, verify

HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
HEX_COMMIT = re.compile(r"[0-9a-f]{40}")


def compare_records(previous, candidate):
    """Reject unsafe or ambiguous upgrade paths; return a human-readable result."""
    for label, record in (("previous", previous), ("candidate", candidate)):
        if not isinstance(record, dict):
            raise ValueError(f"{label} evidence must be an object")
        if (record.get("format") != FORMAT or
            record.get("package") != PACKAGE or
            record.get("artifact_kind") != "debug-alpha-not-for-publication" or
            record.get("release_ready") is not False or
            record.get("physical_device_acceptance") != "not-verified" or
            record.get("network_permission") is not False):
            raise ValueError(f"{label} evidence is not an approved offline debug record")
        if not isinstance(record.get("git_commit"), str) or not HEX_COMMIT.fullmatch(
            record["git_commit"]
        ):
            raise ValueError(f"{label} commit identifier is invalid")
        signer = record.get("signer_certificate_sha256")
        if not isinstance(signer, str) or not HEX_SHA256.fullmatch(signer):
            raise ValueError(f"{label} public signer fingerprint is missing or invalid")
        version = record.get("version_code")
        if type(version) is not int or version < 1:
            raise ValueError(f"{label} versionCode must be a positive integer")
        if (not isinstance(record.get("version_name"), str) or
            not record["version_name"].endswith("-dev")):
            raise ValueError(f"{label} is not a development build")

    if previous["signer_certificate_sha256"] != candidate["signer_certificate_sha256"]:
        raise ValueError(
            "signing certificate changed: in-place Android upgrade may be rejected; "
            "do NOT uninstall a real-data installation to bypass this"
        )
    if candidate["version_code"] <= previous["version_code"]:
        raise ValueError(
            "candidate versionCode must increase; same-version/downgrade "
            "install paths are not accepted by this preflight"
        )
    if candidate["git_commit"] == previous["git_commit"]:
        raise ValueError("candidate is not a distinct source revision")
    return (
        "PASS: both evidenced debug APKs share package and public signer identity, "
        "and candidate versionCode increases. This is NOT handset upgrade approval."
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--previous-apk", required=True, type=pathlib.Path)
    parser.add_argument("--previous-evidence", required=True, type=pathlib.Path)
    parser.add_argument("--candidate-apk", required=True, type=pathlib.Path)
    parser.add_argument("--candidate-evidence", required=True, type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        previous = json.loads(args.previous_evidence.read_text(encoding="utf-8"))
        candidate = json.loads(args.candidate_evidence.read_text(encoding="utf-8"))
        # Verify both exact APK byte streams and embedded JNI/web assets against
        # the paired manifests before comparing untrusted manifest fields.
        verify(args.previous_apk, args.previous_evidence, previous["git_commit"])
        verify(args.candidate_apk, args.candidate_evidence, candidate["git_commit"])
        print(compare_records(previous, candidate))
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError, zipfile.BadZipFile) as exc:
        print(f"BLOCKED: SHIORI debug upgrade preflight: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
