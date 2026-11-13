#!/usr/bin/env python3
"""M2.4c Android *emulator* smoke (NOT a physical-phone test).

Uses only Android SDK platform tools and Python standard library. The APK is
the exact artifact produced by the separate successful android-alpha job.
The smoke checks launch, Activity recreation, force-stop and relaunch, and
real-device accessibility of the offline bundled WebView.

The optional dialog interaction only runs if UIAutomator exposes the WebView
accessibility nodes on this system image; skipped interaction is reported,
never falsely counted as verified.
"""
import argparse
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = "dev.cryogenized.shiori"
ACTIVITY = f"{PACKAGE}/.MainActivity"


def adb(*args, timeout=60):
    cmd = ["adb", *args]
    completed = subprocess.run(
        cmd, text=True, capture_output=True, timeout=timeout, check=False
    )
    if completed.returncode:
        raise RuntimeError(
            f"ADB failed: {' '.join(cmd)}: {completed.stderr.strip()[:400]}"
        )
    return completed.stdout


def alive():
    # Android's pidof returns shell status 1 when the process is absent.
    # That is expected before first launch and after a force-stop, not an
    # ADB transport failure.
    check = subprocess.run(
        ["adb", "shell", "pidof", PACKAGE],
        text=True, capture_output=True, timeout=15, check=False,
    )
    if check.returncode == 1:
        return False
    if check.returncode != 0:
        raise RuntimeError("ADB pidof check failed: " + check.stderr.strip()[:200])
    return bool(check.stdout.strip())


def wait_alive(description, timeout_s=25):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if alive():
            print(f"PASS: {description} — SHIORI process is alive")
            return
        time.sleep(0.6)
    raise RuntimeError(f"SHIORI did not start after {description}")


def launch(label):
    result = adb("shell", "am", "start", "-W", "-n", ACTIVITY)
    if "Error" in result:
        raise RuntimeError(f"Android Activity launch error: {result}")
    wait_alive(label)


def xml_nodes():
    try:
        adb("shell", "uiautomator", "dump", "/sdcard/shiori-emulator-ui.xml", timeout=75)
        xml = adb("shell", "cat", "/sdcard/shiori-emulator-ui.xml")
        return list(ET.fromstring(xml).iter("node"))
    except (RuntimeError, ET.ParseError, subprocess.TimeoutExpired) as err:
        print(f"UIAutomator not ready: {err}", file=sys.stderr)
        return []


def visible_node(nodes, label):
    for node in nodes:
        if node.attrib.get("text") == label or node.attrib.get("content-desc") == label:
            return node
    return None


def tap_node(node):
    bounds = node.attrib.get("bounds", "")
    match = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds)
    if not match:
        raise RuntimeError(f"Cannot tap accessibility node with bounds {bounds!r}")
    x1, y1, x2, y2 = map(int, match.groups())
    adb("shell", "input", "tap", str((x1 + x2) // 2), str((y1 + y2) // 2))


def optional_dialog_probe():
    # A true Android WebView accessibility tap uses OS UIAutomator nodes;
    # browser-origin Playwright remains the authoritative web interaction CI.
    nodes = xml_nodes()
    opener = visible_node(nodes, "New task")
    if opener is None:
        print("SKIP: emulator image did not expose New task accessibility node; "
              "dialog gesture remains a real-device QA gate")
        return
    tap_node(opener)
    time.sleep(1)
    nodes = xml_nodes()
    close = visible_node(nodes, "Close new task without saving")
    if close is None:
        raise RuntimeError("Tapping New task did not expose accessible modal close")
    tap_node(close)
    time.sleep(1)
    nodes = xml_nodes()
    if visible_node(nodes, "Close new task without saving") is not None:
        raise RuntimeError("Modal X failed to dismiss Android WebView task creation")
    print("PASS: native UIAutomator tap opens and dismisses the task modal")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("apk", type=Path)
    p.add_argument("--test-apk", required=True, type=Path)
    args = p.parse_args()
    for target in (args.apk, args.test_apk):
        if not target.is_file() or target.stat().st_size == 0:
            p.error(f"the downloaded Android APK is missing/empty: {target}")
    try:
        adb("wait-for-device")
        adb("install", "-r", str(args.apk.resolve()), timeout=100)
        launch("cold launch")
        time.sleep(2)
        optional_dialog_probe()

        # Rotate, wait for the Activity to be recreated and ensure its
        # process stays available with the existing offline task source.
        adb("shell", "settings", "put", "system", "accelerometer_rotation", "0")
        adb("shell", "settings", "put", "system", "user_rotation", "1")
        time.sleep(2)
        wait_alive("rotation and Activity recreation")

        adb("shell", "am", "force-stop", PACKAGE)
        if alive():
            raise RuntimeError("force-stop failed to terminate SHIORI")
        adb("shell", "settings", "put", "system", "user_rotation", "0")
        launch("force-stop and clean relaunch")
        time.sleep(2)
        if not alive():
            raise RuntimeError("SHIORI crashed immediately after relaunch")

        # A plain Back press with no modal should not produce an ANR or crash.
        adb("shell", "input", "keyevent", "KEYCODE_BACK")
        time.sleep(1)
        launch("Back navigation followed by relaunch")

        # This smoke deliberately rotates the device to landscape, then
        # restores its user setting. On API 35 a settings write alone may not
        # commit the WindowManager display rotation immediately. Lock actual
        # portrait orientation before asserting the mobile FAB is visible.
        # 'cmd window user-rotation' is the WindowManager command supported
        # by Android 12+; this test targets Android 15.
        adb("shell", "cmd", "window", "user-rotation", "lock", "0")
        time.sleep(2)

        # The AndroidX test APK injects genuine device screen-pointer touches
        # into the packaged offline WebView. The instrumented tests inspect
        # DOM/storage after those Android events; they do not call JS click().
        # A test failure can still return an ADB exit code of zero, so insist
        # on the JUnit summary as well as absence of failure markers.
        adb("install", "-r", str(args.test_apk.resolve()), timeout=100)
        runner = (
            "dev.cryogenized.shiori.test/"
            "androidx.test.runner.AndroidJUnitRunner"
        )
        report = adb("shell", "am", "instrument", "-w", "-r", runner, timeout=240)
        if ("FAILURES!!!" in report or "INSTRUMENTATION_FAILED" in report or
                not re.search(r"OK \\(2 tests?\\)", report)):
            raise RuntimeError(
                "Android WebView touch instrumentation failed or skipped tests: "
                + report[-2400:]
            )
        print("PASS: both Android instrumentation tests used real pointer touches "
              "and verified cancellation, task persistence and Activity recreation")

        print("M2.5b emulator lifecycle and Android touch tests passed. This is NOT "
              "physical-phone validation; document-picker and filesystem "
              "fault injection still require real-device QA.")
    except (RuntimeError, subprocess.TimeoutExpired) as err:
        print(f"FAILED Android emulator smoke: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
