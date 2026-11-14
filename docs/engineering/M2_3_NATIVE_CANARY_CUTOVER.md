# M2.3 — guarded native SQLite task-source cutover (debug pilot only)

**Status: EXPERIMENTAL, DEBUG APK ONLY, NOT PRODUCTION-READY.**

M2.3 introduces an opt-in normal-task-UI source pilot using canonical Rust/SQLite. It is never selected automatically for a new installation and cannot be enabled in a non-debuggable Android build. This does NOT claim physical-phone safety verification or deployment readiness.

## One-time opt-in activation

Settings → **Enable Rust task source · debug only** triggers an Android-native warning dialog. Accepting the warning is permission to attempt a cutover, NOT permission to discard original data. On a serial I/O executor, Kotlin then:

1. Reads the **current legacy Android JSON snapshot** from the bundled WebView origin using the dedicated read-only export callback.
2. Calls Rust's M2.2 cutover preflight against an independently named candidate. Every canonical field, task tag, saved-view definition and sort mode must match; unexpected future fields or a stale source make `ready=false` and block activation.
3. Saves and reads back a separate `shiori-legacy-cutover-rollback-v1.sqlite3` JSON safety snapshot. Existing rollback snapshots are never overwritten.
4. Creates a separate, verified SQLite `VACUUM INTO` copy of the candidate at `shiori-native-primary-canary-v1.sqlite3`, leaving the candidate intact. The copy must pass the existing read-only SQLite integrity, schema, FK and original-archive checks.
5. Commits native-source selection to Android SharedPreferences only after these checks succeed, then asks the WebView to load the native source over the typed, one-at-a-time allowlisted JNI bridge.

The legacy Android localStorage task array and earlier native test working copy are never overwritten. There is no network dependency or automatic reconciliation.

## Normal task UI

With native selected, the app fetches canonical tasks through the existing bounded 50-row pagination and mutation-aware snapshot tokens, plus `metadata` for tags and saved workspace preferences. It refuses partial/duplicate/stale records. Normal task create, full edit, version-checked status, deletion and board status moves use the Rust SQLite domain and **do not call WebView `save()`**. The UI shows an explicit source banner, not a visually indistinguishable legacy list.

Original task tags are displayed using native SQLite metadata. The current edit dialog does not support tag editing; saved-view creation/removal is disabled while native mode is selected. Sort/filter remain available for the current session but native preference editing is not yet implemented.

If native loading fails, the normal task list becomes **unavailable** with a clear Settings/rollback prompt. It never falls back silently to legacy records or silently saves a native mutation to localStorage.

## Explicit rollback

Settings → **Return to original Android tasks** asks for confirmation and switches only the UI source selection back to legacy WebView localStorage. The existing native primary database remains on disk, and native-only edits are **not** copied into legacy records. A second cutover with an existing native primary or rollback vault is refused rather than overwriting divergent data. Export the native SQLite backup before rolling back if native edits must be retained.

## Limits and required further validation

**M2.1 physical Android tests remain mandatory:** actual file-provider picker flow, low storage, app termination mid-cutover, APK upgrade/process restart, non-debuggable build refusal, device-specific JNI/SQLite behaviour. Automated Rust, browser-origin and APK packaging CI are necessary but insufficient.

**This is a canary, not final authoritative production migration.** The system still needs proper handling of partial cutover failures and recovery/cleanup, active native saved-view and tag editing, persistence of filter changes in native settings, deterministic conflicts across writers, and robust forward/backward source migration. It also needs a no-data-loss restoration plan for edits made in native mode before production activation.

All three M2.1–M2.3 branches remain **draft stacked PRs**. Do not merge to main without user approval and a verified physical-device test record.
