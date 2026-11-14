#!/usr/bin/env python3
"""Stage and rehearse a SHIORI debug APK upgrade on a *fresh emulator only*.

Never uninstall, clear app data, root a device or fetch private record content.
A real handset, an already-installed package at staging, an unsigned/different-
signer APK, a missing CI manifest or more than one connected device fail closed.

Stage: verify both APKs, install baseline on fresh emulator, invite synthetic
tasks, persist provenance (not task data) outside the source repository.
Upgrade: re-verify provenance and emulator, inspect private-file hashes,
run adb install -r, relaunch, inspect again, and record a sanitized report.
The report does NOT certify real-device acceptance or data correctness.
"""
import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

from compare_debug_upgrades import compare_records, verify_against_apk
from verify_recovery_device import APP_ID, PROTECTED, RECOVERY

ACTIVITY = f"{APP_ID}/.MainActivity"
FORMAT = "shiori-m2-8-emulator-upgrade-stage-v1"
REPORT_FORMAT = "shiori-m2-8-emulator-upgrade-report-v1"


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def adb(*args, timeout=45):
    proc = subprocess.run(
        ["adb", *args], capture_output=True, text=True, timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "ADB command failed (no uninstall/fallback was attempted): " +
            proc.stderr.strip()[:230]
        )
    return proc.stdout


def require_fresh_emulator(serial):
    if not re.fullmatch(r"emulator-[0-9]+", serial):
        raise RuntimeError("Refusing any Android serial not named emulator-NNNN")
    output = adb("devices")
    devices = []
    for line in output.splitlines()[1:]:
        fields = line.strip().split()
        if fields:
            if len(fields) < 2:
                raise RuntimeError("Ambiguous ADB device listing")
            devices.append((fields[0], fields[1]))
    if devices != [(serial, "device")]:
        raise RuntimeError("Exactly one connected and online disposable emulator is required")
    if adb("-s", serial, "shell", "getprop", "ro.kernel.qemu").strip() != "1":
        raise RuntimeError("ADB target is not verified as an Android emulator")
    return serial


def installed_version(serial):
    output = adb("-s", serial, "shell", "pm", "path", APP_ID)
    if not output.strip():
        return None
    if not output.strip().startswith("package:"):
        raise RuntimeError("Could not establish installed SHIORI package")
    dump = adb("-s", serial, "shell", "dumpsys", "package", APP_ID)
    values = set(re.findall(r"\bversionCode=(\d+)\b", dump))
    if len(values) != 1:
        raise RuntimeError("Installed SHIORI versionCode is missing or ambiguous")
    return int(next(iter(values)))


def verify_pair(args):
    prev = json.loads(args.previous_evidence.read_text(encoding="utf-8"))
    next_ = json.loads(args.candidate_evidence.read_text(encoding="utf-8"))
    verify_against_apk(
        args.previous_apk, args.previous_evidence,
        prev, args.aapt, args.apksigner,
    )
    verify_against_apk(
        args.candidate_apk, args.candidate_evidence,
        next_, args.aapt, args.apksigner,
    )
    compare_records(prev, next_)
    return prev, next_


def private_metadata(serial):
    names = (*PROTECTED, RECOVERY)
    script = (
        "cd files || exit 3; for f in " + " ".join(names) + "; do " +
        'if [ -f "$f" ]; then ' +
        'bytes=$(wc -c < "$f"); ' +
        'hash=$(sha256sum "$f" | cut -d " " -f 1); ' +
        'printf "%s|%s|%s\\n" "$f" "$bytes" "$hash"; ' +
        'else printf "%s|absent|absent\\n" "$f"; fi; done'
    )
    out = adb("-s", serial, "shell", "run-as", APP_ID, "sh", "-c", script)
    result = {}
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) != 3 or parts[0] not in names or parts[0] in result:
            raise RuntimeError("Incomplete or duplicated private metadata response")
        name, size, digest = parts
        if size == digest == "absent":
            result[name] = None
        elif size.isdigit() and re.fullmatch(r"[0-9a-f]{64}", digest):
            result[name] = {"bytes": int(size), "sha256": digest}
        else:
            raise RuntimeError("Malformed private SQLite hash response")
    if set(result) != set(names):
        raise RuntimeError("Not all expected private SQLite paths were inspected")
    return result


def webview_size(serial):
    # Only aggregate byte counts, never LevelDB contents or task titles.
    script = (
        'if [ -d "app_webview/Default/Local Storage" ]; then ' +
        'du -sk "app_webview/Default/Local Storage" | cut -f 1; ' +
        'else echo absent; fi'
    )
    raw = adb("-s", serial, "shell", "run-as", APP_ID, "sh", "-c", script).strip()
    if raw == "absent":
        return None
    if not raw.isdigit():
        raise RuntimeError("Malformed WebView storage size response")
    return int(raw)


def save_new_json(path, value):
    # Refuse overwrites and restrict even hash-only metadata to this user.
    # os.open with O_EXCL avoids racing another test run or overwriting output.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def stage(args, prev, next_):
    if args.state_file.exists():
        raise RuntimeError("Stage file already exists; refusing to install over an old trial")
    require_fresh_emulator(args.serial)
    if installed_version(args.serial) is not None:
        raise RuntimeError(
            "SHIORI already installed on emulator; refusing to replace or uninstall it"
        )
    adb("-s", args.serial, "install", str(args.previous_apk.resolve()), timeout=100)
    if installed_version(args.serial) != prev["version_code"]:
        raise RuntimeError("Baseline install did not report the expected versionCode")
    adb("-s", args.serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
    save_new_json(args.state_file, {
        "format": FORMAT, "serial": args.serial,
        "previous_apk_sha256": sha256_file(args.previous_apk),
        "candidate_apk_sha256": sha256_file(args.candidate_apk),
        "previous_commit": prev["git_commit"],
        "candidate_commit": next_["git_commit"],
        "signer_certificate_sha256": prev["signer_certificate_sha256"],
        "previous_version_code": prev["version_code"],
        "candidate_version_code": next_["version_code"],
        "physical_device_acceptance": "not-verified",
        "release_ready": False,
    })
    print("STAGED on disposable emulator only. Create synthetic tasks, edit one, "
          "save a view and verify a separate backup. Run upgrade with "
          "--confirm-synthetic-data when ready; no real data was accessed.")


def upgrade(args, prev, next_):
    if not args.confirm_synthetic_data:
        raise RuntimeError("Upgrade requires --confirm-synthetic-data")
    if args.report.exists():
        raise RuntimeError("Report already exists; refusing to overwrite a previous trial")
    state = json.loads(args.state_file.read_text(encoding="utf-8"))
    expected = {
        "format": FORMAT, "serial": args.serial,
        "previous_apk_sha256": sha256_file(args.previous_apk),
        "candidate_apk_sha256": sha256_file(args.candidate_apk),
        "previous_commit": prev["git_commit"],
        "candidate_commit": next_["git_commit"],
        "signer_certificate_sha256": prev["signer_certificate_sha256"],
        "previous_version_code": prev["version_code"],
        "candidate_version_code": next_["version_code"],
        "physical_device_acceptance": "not-verified",
        "release_ready": False,
    }
    if state != expected:
        raise RuntimeError("Emulator trial provenance changed; refusing to install candidate")
    require_fresh_emulator(args.serial)
    if installed_version(args.serial) != prev["version_code"]:
        raise RuntimeError("Installed baseline version differs; no candidate was installed")

    # Quiesce the app before taking a read-only, hash-only baseline.
    adb("-s", args.serial, "shell", "am", "force-stop", APP_ID)
    before = private_metadata(args.serial)
    before_webview = webview_size(args.serial)
    adb("-s", args.serial, "install", "-r",
        str(args.candidate_apk.resolve()), timeout=100)
    if installed_version(args.serial) != next_["version_code"]:
        raise RuntimeError("Candidate in-place install did not set expected versionCode")
    adb("-s", args.serial, "shell", "am", "start", "-W", "-n", ACTIVITY)
    adb("-s", args.serial, "shell", "am", "force-stop", APP_ID)
    after = private_metadata(args.serial)
    after_webview = webview_size(args.serial)

    missing = [name for name in before if before[name] is not None and after[name] is None]
    changed = [name for name in PROTECTED if before[name] != after[name]]
    report = {
        "format": REPORT_FORMAT, "emulator_serial": args.serial,
        "baseline_version_code": prev["version_code"],
        "candidate_version_code": next_["version_code"],
        "signer_certificate_sha256": prev["signer_certificate_sha256"],
        "baseline_private_hashes": before,
        "candidate_private_hashes": after,
        "changed_private_files": changed,
        "missing_private_files": missing,
        "webview_store_kib_before": before_webview,
        "webview_store_kib_after": after_webview,
        "physical_device_acceptance": "not-verified",
        "release_ready": False,
        "manual_task_parity": "pending",
        "manual_provider_testing": "pending",
    }
    save_new_json(args.report, report)
    if missing or (before_webview is not None and after_webview is None):
        raise RuntimeError("WARNING: app-private storage vanished; inspect report, do not approve")
    print("PASS: same-signer in-place APK upgrade completed on a verified disposable "
          "emulator; metadata report saved. App tasks, edits, tags, views, "
          "recovery and backup still require manual parity validation. "
          "No physical-device approval or production release.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("stage", "upgrade"))
    parser.add_argument("--serial", required=True)
    parser.add_argument("--previous-apk", required=True, type=pathlib.Path)
    parser.add_argument("--previous-evidence", required=True, type=pathlib.Path)
    parser.add_argument("--candidate-apk", required=True, type=pathlib.Path)
    parser.add_argument("--candidate-evidence", required=True, type=pathlib.Path)
    parser.add_argument("--aapt", default="aapt")
    parser.add_argument("--apksigner", default="apksigner")
    parser.add_argument("--state-file", required=True, type=pathlib.Path)
    parser.add_argument("--report", type=pathlib.Path)
    parser.add_argument("--confirm-disposable-emulator", action="store_true")
    parser.add_argument("--confirm-synthetic-data", action="store_true")
    args = parser.parse_args(argv)
    if not args.confirm_disposable_emulator:
        parser.error("an explicit --confirm-disposable-emulator is required")
    if args.action == "upgrade" and args.report is None:
        parser.error("upgrade requires --report")
    try:
        prev, next_ = verify_pair(args)
        if args.action == "stage":
            stage(args, prev, next_)
        else:
            upgrade(args, prev, next_)
    except (OSError, ValueError, RuntimeError, TypeError, KeyError,
            subprocess.TimeoutExpired, json.JSONDecodeError) as err:
        print(f"BLOCKED: Android emulator upgrade rehearsal: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
