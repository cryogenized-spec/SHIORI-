# SHIORI M2.8 — disposable emulator in-place upgrade rehearsal

**Status: development tool, not production acceptance.** This is a real
Android package-manager upgrade rehearsal on a **fresh Android emulator
only**. It does not run on a physical handset or existing SHIORI test
installation, and it never calls `adb uninstall`, `pm clear`, or root.

## Prerequisites

Build two distinct SHIORI debug commits using the **same privately held
external development keystore** and strictly increasing `versionCode`.
The build output/CI artifact for each commit needs its own matching
`shiori-android-evidence.json`. See [M2.7 development signing](M2_7_STABLE_DEV_SIGNING.md)
and [M2.6 independent APK preflight](M2_6_ANDROID_UPGRADE_PREFLIGHT.md).

Use a separate disposable AVD with no SHIORI installation, task records, or
personal login. Start it and run `adb devices`. The helper refuses any serial other than `emulator-NNNN`, rejects
`ro.kernel.qemu != 1`, and requires **exactly one connected device**.
It also binds the two stages to the same Android kernel boot identity and a
random installation-specific marker in the test app's private directory.
Do **not** stop/reboot the AVD or switch to another emulator between stages;
a re-used `emulator-5554` serial cannot substitute for the staged instance.
With a phone connected too, disconnect the phone before testing.

The helper independently checks the actual APK signer and version via SDK
`aapt` and `apksigner`, validates both complete CI evidence manifests,
checks the common public signer digest, and refuses a non-increasing
versionCode. It will not generate or store signing keys.

## Step 1: stage the baseline

```bash
python3 tools/android/rehearse_emulator_upgrade.py stage \
  --serial emulator-5554 \
  --previous-apk /tmp/shiori-old/app-debug.apk \
  --previous-evidence /tmp/shiori-old/shiori-android-evidence.json \
  --candidate-apk /tmp/shiori-new/app-debug.apk \
  --candidate-evidence /tmp/shiori-new/shiori-android-evidence.json \
  --aapt "$ANDROID_HOME/build-tools/36.0.0/aapt" \
  --apksigner "$ANDROID_HOME/build-tools/36.0.0/apksigner" \
  --state-file /tmp/shiori-upgrade-stage.json \
  --confirm-disposable-emulator
```

This installs **only the previous APK** on a fresh emulator, creates a
random test-only marker under that installation's private app directory,
launches SHIORI, and writes a non-sensitive stage manifest outside the repository.
It will not overwrite an existing stage file or an existing app package.
If it fails after installing the baseline, reset or recreate the disposable
AVD; never work around the refusal by deleting a real installation.

Manually create several *synthetic* tasks, edit and complete one, save a
view, change sorting and save an independent JSON or SQLite export using
SHIORI's own settings. Verify the contents before continuing. The script
does not invent data or assert that human checks passed.

## Step 2: perform a same-package upgrade, with no uninstall

```bash
python3 tools/android/rehearse_emulator_upgrade.py upgrade \
  --serial emulator-5554 \
  --previous-apk /tmp/shiori-old/app-debug.apk \
  --previous-evidence /tmp/shiori-old/shiori-android-evidence.json \
  --candidate-apk /tmp/shiori-new/app-debug.apk \
  --candidate-evidence /tmp/shiori-new/shiori-android-evidence.json \
  --aapt "$ANDROID_HOME/build-tools/36.0.0/aapt" \
  --apksigner "$ANDROID_HOME/build-tools/36.0.0/apksigner" \
  --state-file /tmp/shiori-upgrade-stage.json \
  --report /tmp/shiori-emulator-upgrade-report.json \
  --confirm-disposable-emulator \
  --confirm-synthetic-data
```

The helper checks that the installed baseline matches the stage file and
the current APKs. It force-stops SHIORI to quiesce file writes, records
**only SHA-256 and sizes** of the protected app-private SQLite files, and
checks the approximate size of the WebView local-storage directory. It
**writes that baseline into the reserved 0600 report before any upgrade**,
then runs `adb install -r` with the candidate APK, verifies the new
versionCode, launches the application, and waits for bounded, read-only
evidence of a live foreground process and stable persisted WebView/private
storage across multiple observations before taking the post-upgrade snapshot. It rejects missing protected databases and complete
disappearance of a previously present WebView directory.

If the install, app launch, readiness check or final metadata inspection
fails, the report retains the baseline hashes, an incomplete status and the
last failed phase. This makes an interrupted attempt inspectable even though
the same version cannot simply be reinstalled as a fresh trial. Readiness is
a filesystem/window liveness gate, **not** proof that every JavaScript
callback or native database operation completed.

A successful package-manager upgrade is **not** data integrity
confirmation. The report explicitly records
`physical_device_acceptance=not-verified`,
`release_ready=false`, `manual_task_parity=pending` and
`manual_provider_testing=pending`. Some SQLite hashes may change during
normal app startup even if records are preserved; every changed private
file must be inspected manually. No private SQLite bytes, task titles,
notes or signing secrets are exported by this helper.

## Manual closeout

Open the upgraded test app and verify the synthetic tasks, statuses,
timestamps, tags, saved views, FIFO ordering, attached native preview,
backups, explicit rollback, document picker cancellation and force-stop
persistence. Record expected versus observed counts and any differences
in an appropriately restricted QA record. Do not label this physical
device acceptance, and do not publish either APK.

The remaining release gates include real handset keyboard/gesture QA,
accessibility, document-provider interruption and storage-fault testing,
external signing-key custody, privacy review and explicit release
authorization.
