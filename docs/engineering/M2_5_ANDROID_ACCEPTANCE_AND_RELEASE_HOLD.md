# SHIORI M2.5 — Android acceptance, provenance and release-candidate hold

**Status: RELEASE BLOCKED.** This document is a testing plan, not permission to publish, merge stacked PRs or promote the debug APK. M2.4d's Rust/SQLite native primary is still behind a debuggable-build-only user-confirmed cutover. Production use, public distribution and automated migration are **not approved**.

## Evidence automated in CI

The source-job `android-alpha` builds the offline APK, checks the JNI symbols for armv7/arm64/x86_64, validates the packaged assets and refuses network/external-storage permissions. It now runs `tools/android/apk_release_evidence.py create`, which validates the APK's ZIP CRCs, package ID, `-dev` version, signing certificate and the full embedded JNI/asset set. It creates `shiori-android-evidence.json` with SHA-256s of the full APK and individual critical members, plus the exact checkout commit used by CI.

The same `shiori-android-alpha` GitHub Actions artifact contains the debug APK and its evidence manifest. Before launching the emulator, `android-emulator-smoke` downloads **that exact artifact** and runs the independent `verify` command. Missing assets, changed APK bytes, mismatched commit or a falsely asserted physical-device pass fail closed.

**Scope of assurance:** this is internal traceability and byte-integrity against a CI-created manifest, **not independent signed attestation, reproducible-build proof or a production signing process**. The report explicitly fixes `release_ready=false` and `physical_device_acceptance=not-verified`.

## Android signing caveat — do not lose user data

GitHub's debug signing keystore may be regenerated between isolated CI runners. Debug APKs from different runs can therefore be signed by **different certificates**, and Android may reject an in-place update with `INSTALL_FAILED_UPDATE_INCOMPATIBLE`. **Never uninstall SHIORI on a real-data device just to force an upgrade:** uninstalling can destroy the app-private SQLite databases and WebView data, and `android:allowBackup="false"` intentionally disables Android's automatic app-data backup. Export your data to an independently verified external document first; preferably test each CI build on a separate disposable Android user/profile or emulator.

A separately provisioned, securely stored, stable release/development signing identity and a verified **same-package upgrade** are mandatory before shipping to real users. The public certificate SHA-256 in the evidence JSON lets a tester compare build identities without sharing any private key.

## Physical-device acceptance matrix (manual; pending)

Record a pass/fail, Android version, keyboard model, date and sanitized evidence for each. Use disposable records, never personal task titles or exported data in public CI attachments.

- **Fresh installation:** a clean Android profile loads the expected empty personal workspace without network. Debug native canary remains opt-in and does not activate itself.
- **Create, edit and Back/X:** make a task; open edit with the on-screen keyboard. With a short viewport, X and Cancel stay tappable; Android Back dismisses the expected surface; unsaved edits do not reach SQLite. Verify that saved edits survive force-stop/relaunch.
- **Native tags:** under the opt-in native source, save, reorder and clear tags; verify persistence after relaunch, case-insensitive duplicate rejection and stale revision failures.
- **Saved views and sorting:** create/rename (by replacing) and remove views; select FIFO/due/priority/focus sorting; force-stop and relaunch; verify all preferences come from native SQLite. Explicit rollback must restore **original WebView views and sorting**, with no silent merging from native edits.
- **Document provider:** use the Android system picker to save a native SQLite export, and confirm that the document exists independently. Rotate during the picker, cancel/retry, deny destination write and attempt an interrupted picker. No original database can be replaced.
- **Isolated recovery:** on disposable data, record read-only private-file hashes using `tools/android/verify_recovery_device.py snapshot --output /tmp/shiori-before.json`. Stage and inspect a recovery of the exported SQLite backup. Recheck with `verify --baseline /tmp/shiori-before.json`. Hashes must match for **all** non-recovery native databases and WAL/SHM/journal sidecars, including the selected primary and rollback vault. The isolated recovered preview must be new. Original data must remain accessible.
- **Interrupted cutover:** on disposable data, force-stop between candidate creation and user confirmation, then use explicit debug recovery. Stale legacy archives, invalid candidates, existing overwritten destinations and edited primary data must be rejected; do not copy user data into public reports.
- **Device and storage faults:** use an isolated emulator/test profile for low-space/failing provider injection, not a personal handset. No destructive test on working records.
- **Accessibility:** inspect font scaling, touch targets, screen-reader announcements, soft keyboard layout, and reduced-motion behaviour on at least one real device.

**The CI Android emulator job is not a substitute for the above**. Its UIAutomator direct New Task interaction is allowed to skip when accessibility nodes are unavailable; the log must show that skip rather than misrepresent it as a pass.

## Test helper

With a USB/ADB-connected device running the debug package and a **disposable test profile**:

```bash
python3 tools/android/verify_recovery_device.py snapshot --output /tmp/shiori-before.json
# On Android: export an independent SQLite backup, select the backup and
# use "Stage isolated SQLite recovery"; inspect the recovered preview.
python3 tools/android/verify_recovery_device.py verify --baseline /tmp/shiori-before.json
```

The helper runs read-only `adb shell run-as` size/SHA checks. It does not copy task contents, mutate app files, control Android screens or claim to have tested any phone unless actually invoked on one. Its snapshots are **v2** and contain no task data. An incomplete/older manifest is intentionally rejected.

## M2 closeout / explicit approval gates

M2 cannot be declared complete while any of the following is open: physical-device QA, direct UIAutomator touch skip, document-provider fault tests, review of the privacy/export text, stable signing and upgrade-safety, or review of the full stacked draft PR chain. PR #24 and this M2.5 draft remain independent; no merge is authorized. The future production release needs its own controlled signing pipeline, independent security review and explicit owner approval.
