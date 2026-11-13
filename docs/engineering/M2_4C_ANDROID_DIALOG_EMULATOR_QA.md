# M2.4c — Android keyboard/modals and real emulator smoke

**Target:** improve everyday task capture and editing while preserving the offline app and the debug-only Rust/SQLite storage cutover boundary.

## Touch and keyboard reliability

- The Android Activity uses `windowSoftInputMode="adjustResize"` so the bundled WebView can shrink when the soft keyboard appears, rather than painting the bottom of a dialog behind the keyboard.
- Creation/edit modals retain the triggering control as their focus-return target. Android Back, the on-screen X, Cancel, or Escape dismisses one dialog and restores focus to a visible connected opener.
- Modal keyboard Tab and Shift+Tab stay inside the active dialog. Global shortcuts (such as “n” for New task and “/” for search) cannot open other surfaces while a dialog is active.
- Delayed JavaScript autofocus checks that the modal is still open before focusing; dismissing a dialog immediately cannot later focus its hidden input.
- All unsaved changes are discarded when a dialog closes, with no native JNI write or localStorage update.

Playwright on the Android asset-origin tests short viewport (390×470, representing a soft keyboard), direct X/Cancel clicks, focus restoration, keyboard wrap-around and abandoning an edited task without changing its stored title.

## Real Android emulator, not just simulated browser origin

The Android GitHub Actions workflow now performs two separate jobs:

1. Build the same debug APK as before, including the Rust JNI library for supported Android ABIs and permissions checks.
2. Download **that exact APK artifact**, start an Android 15 / API 35 x86_64 emulator using a pinned and verified runner action, then use ADB to install and launch the packaged app.

`tests/android_emulator_smoke.py` checks cold startup, force-stop/relaunch, rotation/Activity recreation, Android Back and another launch. It probes native UIAutomator accessibility: if the emulator exposes the New task node, it taps the actual WebView control and verifies that X dismisses the modal. If accessibility nodes are unavailable on this system image, it records the skip and **does not claim dialog interaction was tested**.

This emulator is a real Android runtime on CI, but **not a physical handset**. Hardware manufacturers, soft keyboards, physical memory/low-storage conditions, and document providers can behave differently.

## Physical-phone acceptance checklist

With a disposable test profile or a prior complete export, install the Android Alpha APK from the latest passing Actions artifact and verify:

1. Create a task, type text into the notes field, rotate with the soft keyboard raised, then dismiss via X and confirm the unsaved record was not created.
2. Use Android system Back once to dismiss the keyboard (where supported), again to dismiss the modal, and confirm the task list remains accessible.
3. Open an existing task, begin editing, scroll to the bottom with the keyboard open, then use Cancel; confirm the original title/notes remain unchanged. Repeat and save to confirm persistence after force-stop.
4. Switch to the debug native canary only on disposable data. Verify its task editor and explicit rollback, and the refusal to overwrite an edited primary during interrupted recovery.
5. Export to a third-party Android DocumentsProvider, rotate during the picker, finish the export and inspect an isolated SQLite recovery. Cancel, disconnect or deny permissions, and test low storage; no original data may be changed.
6. Record whether the screenshot, keyboard geometry and Back behaviour differ across your actual device and the CI emulator.

**Still required before production:** physical-device validation and a robust instrumented document-provider fault-injection suite, provider-independent native tag/saved-view editing, and explicit approval of the staged PR chain. The debug canary remains gated; no `INTERNET` or broad external storage permission is added.
