# Android Rust/SQLite safety-vault slice (M2, experimental)

This branch introduces **real Rust code cross-compiled into the Android APK**
and a transactional private SQLite snapshot vault. It is an intentionally
non-destructive bridge toward a shared Rust task storage engine.

## Current architecture

- The existing SHIORI Android UI still edits and reads WebView localStorage.
  Existing phone records and prior JSON export/restore remain intact.
- A Rust `cdylib` (`crates/shiori-android-native`) is packaged for
  `armeabi-v7a`, `arm64-v8a`, and `x86_64`. The Kotlin-only
  `NativeVault` object invokes two small JNI entrypoints; **no JNI method
  is injected as a JavaScriptInterface**.
- The only browser-native signal is a custom `shiori-vault://` navigation
  intercepted by the Android Activity. Kotlin requests the current backup
  payload with `evaluateJavascript` and passes it to Rust on a serialized
  I/O worker.
- Rust validates format, data types, task IDs, priority/status, due calendar
  dates, sizes, and view entries before committing **one** private SQLite
  record. Malformed writes leave the previous snapshot unchanged.
- On launch, Kotlin checks the Rust vault. If **no** snapshot exists, it
  saves the current WebView records as an initial copy. An **existing**
  snapshot is **never replaced on page startup**. This protects records
  when WebView localStorage is unexpectedly unavailable.
- On task changes, manual JSON restores, named view changes, and task-sort
  changes, the browser requests another safety copy. Manual **Save native
  safety copy** and **Recover native safety copy** actions are also available
  under Settings → Your data. Recovery requires an Android confirmation.

The new private SQLite file is `filesDir/shiori-rust-snapshot.sqlite3`.
It deliberately **does not** use the canonical `shiori-storage` task schema
yet: the browser's legacy JSON records are not `Task` records with the same
IDs, revisions, and tombstones. Bulk-mutating canonical task rows before
writing a lossless migration is unsafe.

## What is verified

- Host Rust tests validate round-trip persistence after database reopen,
  Unicode, format rejection, duplicate IDs, invalid dates and no overwrite
  on bad data.
- CI cross-compiles the Rust library and verifies the native binaries are
  **inside** the APK for all three ABIs.
- Existing Android private-origin browser tests continue to cover task edit,
  creation, completion, backup/restore, cancellation and saved views.
- The APK still requests **no Internet permission** and no broad storage
  permissions.

**Not yet verified on a physical phone:** JNI loader behavior on each ABI,
custom-scheme callback timing, repeated background save reliability, and
Android recovery confirmation. A successful desktop/browser test is not a
substitute for instrumented Android-device tests.

## Next migration requirements

1. Define a complete, lossless mapping of WebView task IDs, statuses, revisions,
   notes, dates, assignments and deleted task tombstones into canonical Rust
   `Task` records.
2. Implement a staged, idempotent migration with independent backup and
   rollback. Never clear the legacy localStorage before the new database
   has passed a read-back/integrity check.
3. Make Rust `shiori-storage` authoritative for Android CRUD through a
   narrowly scoped native transport, then remove the temporary snapshot
   duplication when device tests have passed.
4. Build Android instrumentation tests for JNI, offline startup, process death,
   native read/write/recovery, and runtime permission boundaries. Follow with
   opt-in native notifications.

This branch remains a **draft** and not a production release. No external
network, telemetry, synchronization, or task-data upload is introduced.
