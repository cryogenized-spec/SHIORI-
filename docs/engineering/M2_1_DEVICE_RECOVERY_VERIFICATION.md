# M2.1 — Android backup/recovery verification gate

This stage introduces an executable **real-device smoke harness**, not a claim of having run on an Android phone. SHIORI's existing Rust CI already verifies SQLite `VACUUM INTO` export and isolated restore under WAL, including tombstones, dependencies, metadata provenance and corrupt backup refusal. The new ADB harness helps validate these invariants on a **debug APK on the actual target phone**.

## Device runbook

Install the latest `shiori-android-alpha` debug APK from the successful GitHub Actions build. Enable Android USB debugging and check `adb devices`. Prefer a disposable test installation containing representative test tasks and no irreplaceable data.

1. Create the experimental Rust working copy from Settings and add a few test records. Include a completed task, an editable title, and an existing normal WebView task.
2. Run `python3 tools/android/verify_recovery_device.py snapshot --output /tmp/shiori-baseline.json`. This records SHA-256 digests and file byte counts **only** for the native working database, migration shadow, safety vault and recovered preview. It fails if a previous recovery exists.
3. Use Settings → **Export native SQLite backup**. Choose a local document provider and save the SQLite file. Confirm the Android app reports success.
4. Use Settings → **Stage isolated SQLite recovery**. Pick the file saved in step 3. Confirm the app reports a verified independent preview. Then select **Inspect recovered preview** and check counts and absence of errors.
5. Run `python3 tools/android/verify_recovery_device.py verify --baseline /tmp/shiori-baseline.json`. It asserts that the recovered preview was created and that **no protected database file changed** during the trial. Do not edit tasks between steps 2–5.
6. Close and relaunch SHIORI. The original Android list must remain unchanged; repeat **Inspect recovered preview** and verify that it persists.

The harness requires `run-as`, supported by debug APKs; it does not request root and does not read/copy task contents. Treat its baseline file as potentially device-identifying metadata; keep it out of Git.

## Failure matrix for physical testing

- Cancel the Android document picker: no recovered preview should appear.
- Choose arbitrary text, a truncated SQLite file, a non-v3 SQLite database, or a corrupt SQLite file: reject without changing other files.
- Try staging the same valid backup twice: the second attempt must refuse to overwrite the existing preview.
- Interrupt the Activity or force-stop the app during copy: normal Android tasks and original databases must remain accessible.
- Deny document-provider access or exhaust available storage: display failure; preserve source files.
- Restart the Activity after a successful recovery and inspect the recovered preview again.
- Check Android Back/cancel behaviour, WebView source separation, and lack of new INTERNET/storage permissions.

**Do not delete an existing recovered preview to rerun the test on production data.** Use a disposable debug installation, or add a separately reviewed cleanup feature with backup guarantees.

## Remaining blocking evidence

A fully automated Android instrumented test environment with an emulator/test document provider, and at least one **physical-phone** test of all scenarios, remain outstanding. A passed Rust/Playwright/mock-ADB CI build is not a substitute. M2.3 cutover must remain guarded until these gates and M2.2 parity checks are satisfied.
