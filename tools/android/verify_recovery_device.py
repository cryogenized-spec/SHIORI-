#!/usr/bin/env python3
"""Run a safe, interactive Android *device* recovery check.

The script never reads task contents, installs packages, requests root,
changes database files or removes any data. Requires a debuggable APK
with Android's 'run-as' available and a USB/ADB-connected device.

Workflow:
  python3 tools/android/verify_recovery_device.py snapshot --output /tmp/shiori-before.json
  # On the phone, export a native SQLite backup; then use Settings to
  # stage an isolated recovery of that exported backup and inspect it.
  python3 tools/android/verify_recovery_device.py verify --baseline /tmp/shiori-before.json
"""
import argparse
import json
import pathlib
import subprocess
import sys

APP_ID = "dev.cryogenized.shiori"
PROTECTED = (
    "shiori-native-working-v1.sqlite3",
    "shiori-canonical-preview.sqlite3",
    "shiori-rust-snapshot.sqlite3",
)
RECOVERY = "shiori-native-recovery-preview-v1.sqlite3"


def adb(args):
    process = subprocess.run(
        ["adb", *args], capture_output=True, text=True, check=False, timeout=20
    )
    if process.returncode:
        raise RuntimeError(
            "ADB command failed: check USB debugging, connected device, "
            "installed debug APK and run-as permission. " + process.stderr.strip()[:220]
        )
    return process.stdout


def state():
    # Do not export private data or the backup; only hash and size metadata.
    adb(["get-state"])
    names = (*PROTECTED, RECOVERY)
    script = (
        "cd files || exit 3; "
        "for f in " + " ".join(names) + "; do "
        "if [ -f \"$f\" ]; then "
        "bytes=$(wc -c < \"$f\"); "
        "hash=$(sha256sum \"$f\" | cut -d ' ' -f 1); "
        "printf '%s|%s|%s\\n' \"$f\" \"$bytes\" \"$hash\"; "
        "else printf '%s|absent|absent\\n' \"$f\"; fi; done"
    )
    rows = adb(["shell", "run-as", APP_ID, "sh", "-c", script])
    parsed = {}
    for line in rows.splitlines():
        fields = line.strip().split("|")
        if len(fields) != 3 or fields[0] not in names:
            raise RuntimeError("Unexpected ADB response; declining to interpret device data")
        name, byte_count, digest = fields
        if byte_count == "absent":
            parsed[name] = None
        else:
            if not byte_count.isdigit() or len(digest) != 64:
                raise RuntimeError("Malformed Android size/hash response")
            parsed[name] = {"bytes": int(byte_count), "sha256": digest}
    if set(parsed) != set(names):
        raise RuntimeError("Could not inspect all expected private Android database paths")
    return parsed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["snapshot", "verify"])
    parser.add_argument("--output", type=pathlib.Path)
    parser.add_argument("--baseline", type=pathlib.Path)
    args = parser.parse_args()
    if args.action == "snapshot" and not args.output:
        parser.error("snapshot requires --output")
    if args.action == "verify" and not args.baseline:
        parser.error("verify requires --baseline")

    try:
        if args.action == "snapshot":
            before = state()
            if before[RECOVERY] is not None:
                raise RuntimeError(
                    "A previous recovered preview already exists. Never overwrite "
                    "it for testing. Use a separate, disposable test install."
                )
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump({"app_id": APP_ID, "files": before}, stream, indent=2)
            print("Baseline metadata saved. On the device: export Rust SQLite "
                  "backup, stage isolated recovery, inspect; then run verify.")
        else:
            data = json.loads(args.baseline.read_text(encoding="utf-8"))
            if data.get("app_id") != APP_ID or not isinstance(data.get("files"), dict):
                raise RuntimeError("Baseline is not a SHIORI device snapshot")
            before = data["files"]
            after = state()
            changed = [f for f in PROTECTED if after[f] != before.get(f)]
            recovered = after[RECOVERY]
            if changed:
                raise RuntimeError(
                    "FAILED: these protected SQLite files changed during "
                    "the controlled recovery trial: " + ", ".join(changed)
                )
            if recovered is None or recovered["bytes"] == 0:
                raise RuntimeError("FAILED: no isolated recovered SQLite file was created")
            print("PASS: independent recovered preview exists; original private "
                  "databases retain their pre-recovery sizes and hashes.")
            print("Still verify the recovered record counts in the app's "
                  "'Inspect recovered preview' dialog; this script does not "
                  "prove SQLite integrity, restore correctness or SAF UX.")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Recovery device check did not pass: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
