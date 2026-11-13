# M2.4a — Android lifecycle and verified rollback (experimental)

This PR **does not** activate Rust storage in release builds. All native cutover controls remain debug-only, the legacy WebView store stays on-device, and the previous experimental SQLite databases are not rewritten or deleted.

## Source rollback no longer trusts a single toggle

Before switching back to legacy tasks, Kotlin asks the bundled, trusted WebView page to freeze task mutations and export its current **legacy localStorage records**, even while the native canary is selected. A Rust JNI verifier checks three independently stored sources:

1. the frozen current legacy Android export;
2. the pre-cutover private `shiori-legacy-cutover-rollback-v1.sqlite3` safety vault;
3. the unchanged canonical `shiori-native-cutover-candidate-v1.sqlite3` migration candidate.

The validator opens both databases **read-only**. It verifies SQLite integrity and the vault payload; it also runs the existing canonical migration audit across task fields, ordered tags, saved views and sort mode. JSON equality ignores only the regenerated `exported_at` timestamp. The task source must match both stored references.

A missing or corrupted vault, altered tags/preferences/task details, missing candidate or malformed backup blocks rollback. The application keeps Rust selected and unfreezes the current UI. Source preference is changed only after successful verification. No native edits are automatically copied into WebView; the native primary database remains intact for later export or recovery.

The browser regression covers the new freeze/abort controls and ensures existing WebView localStorage contents do not change. Rust tests cover matched records (including a regenerated export timestamp), missing files without recreating them, corrupt vaults, altered task details/tags/views, and tampering with canonical migration metadata.

## SAF picker recreation

Previously an Android configuration change (for example, rotating the screen while `ACTION_CREATE_DOCUMENT` was open) could destroy the Activity, delete the pending SQLite export and lose the staging reference.

M2.4a stores **only the app-private temporary export path** in Activity saved instance state, not backup bytes or an external document URI. On recreation, it restores that pending export only if the file belongs to the app cache, matches the reserved temporary name and suffix, exists and is within the 64 MiB bound. It preserves that staging file during configuration recreation but deletes it after cancellation, a successful copy, or ordinary Activity destruction. A lost/unavailable staging file is reported instead of silently claiming a successful export. The native recovery-picker-pending flag is also restored.

No broad storage permission, `INTERNET` permission, `addJavascriptInterface`, external document-path access or new network dependency is introduced.

## Real Android device test matrix — REQUIRED BEFORE PRODUCTION

1. Install the debug APK on a disposable test device. Create normal Android test tasks, stage a parity-verified native candidate and activate debug canary.
2. In native mode, make an edit. Confirm it is saved in Rust/SQLite and not merged into WebView.
3. Press **Verify and return to Android tasks**. Confirm original untouched legacy tasks reappear, and that native-only edits remain in the separate native database.
4. Repeat on a disposable test installation after deliberately corrupting or changing only a *copy* of the private rollback source. Verify the rollback refuses to switch. Never corrupt production or irreplaceable personal data.
5. Open **Export native SQLite backup**. While Android's document provider picker is open, rotate the device and return to the app. Complete saving; confirm the output file is valid by staging a separate recovery preview. Repeat with picker cancellation.
6. Repeat source inspection/rollback after force-stop, app relaunch, Android Back gesture, and limited available storage. Check the failure message and preserve all test task sources.
7. Inspect `adb logcat` for crashes, leaks or ANRs and verify the offline permission gate. Do not infer hardware validation from GitHub Actions.

**Limitations:** Kotlin configuration restoration still requires real device validation. Process death in the middle of native verification, on-device storage exhaustion, and forward reactivation after rollback need explicit product policy and separate QA. A green CI run verifies compilation and browser/Rust tests, not every Android lifecycle event.
