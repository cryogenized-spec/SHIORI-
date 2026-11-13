# Android M2: non-overwriting recovery of exported native SQLite

**Status: experimental recovery staging, not activation.**

This increment supports selecting a previously exported `SHIORI-native-working-backup.sqlite3` file and restoring it into an **independent, inactive SQLite recovery preview**. It deliberately cannot overwrite or activate the existing Android WebView task store, active native working database, legacy safety vault, or canonical migration shadow.

## Workflow

From Android Settings, choose **Stage isolated SQLite recovery**. The native Activity explains that the operation will never replace active records. Android `ACTION_OPEN_DOCUMENT` lets the user select a file supplied by a document provider. The picker uses `*/*` to accommodate providers that label SQLite backups `application/octet-stream`.

Kotlin reads and bounds the selected bytes to **64 MiB**, storing them temporarily in the app-private cache. No provider URL, input URI or private path enters WebView JavaScript. The native Rust JNI operation checks that the input file exists, is non-empty, is within size limits, uses canonical schema v3, passes a full SQLite `integrity_check`, has valid foreign-key relationships, and contains a valid original Android JSON source archive. Unexpected SQL triggers or views are rejected.

Rust uses `VACUUM INTO` to construct a fresh database at a new private staging path. It then reopens the copy read-only and compares its manifest, complete canonical task field values (including revisions and deletion markers), dependency records and archived original JSON against the source. Validation failure removes only the new staging output; no established database is touched.

Only after successful verification does Kotlin rename that completed private staging file to its single reserved recovered location:

`filesDir/shiori-native-recovery-preview-v1.sqlite3`

That path is **different** from:

- `filesDir/shiori-native-working-v1.sqlite3` (editable experimental native task engine)
- `filesDir/shiori-canonical-preview.sqlite3` (migration shadow)
- `filesDir/shiori-rust-snapshot.sqlite3` (legacy safety vault)
- the Android WebView localStorage task source

A pre-existing recovered preview is never overwritten by another import. Staging and read/write operations run on a serial I/O worker. The app can also **Inspect recovered preview** after reopening: this calls a separate read-only JNI integrity/metadata check and displays counts of records, soft-deleted records and dependencies.

## Security and failure boundaries

The selected SQLite bytes are **untrusted input**. Validation is performed on a separate file; the database is not attached to the current task connection, promoted to normal task storage, or registered as a writable JS endpoint. A corrupt, incompatible, over-size, foreign-key-invalid or suspicious backup is rejected. Original Android JSON backups and live tasks are unaffected by recovery attempts, document-picker cancellation or a failed source inspection.

Recovered databases are **not encrypted**. Users should store exported backup files in trusted locations; remote document-provider retention is not guaranteed.

This feature does not yet implement a rollback/import into the authoritative task store, merge or task synchronization. The recovered preview is available for integrity inspection and later controlled recovery work, not for normal editing.

## Validation and limitations

Rust tests cover successful full-record recovery from a previously exported SQLite file (including deleted records, dependencies, legacy archive), preservation of the original and exported files, refusal to overwrite existing recovery files, rejection of corrupt/old-schema files, invalid foreign keys, and unexpected triggers. CI also builds the updated Android JNI exports for each configured ABI and runs browser-origin UI tests.

**A passing CI build is not physical Android testing.** Device validation must exercise SAF document providers, picker cancellation, process death between staging and rename, low storage, and actual recovery inspection on a reopened Activity.

A future controlled storage cutover requires proof of complete task/view/tag parity, explicit user approval, backup verification, native editing parity, and a rollback path. No PR in the stacked draft chain may be merged without approval.
