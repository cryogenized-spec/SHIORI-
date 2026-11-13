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
    args = p.parse_args()
    if not args.apk.is_file() or args.apk.stat().st_size == 0:
        p.error("the downloaded Android APK is missing/empty")
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

        print("M2.4c emulator launch/lifecycle smoke passed. This is NOT "
              "physical-phone validation; document-picker and filesystem "
              "fault injection still require real-device QA.")
    except (RuntimeError, subprocess.TimeoutExpired) as err:
        print(f"FAILED Android emulator smoke: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
