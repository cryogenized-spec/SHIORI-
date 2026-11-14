# Android M2: independently exported Rust working-copy SQLite backup

**Status:** export-only, opt-in and experimental. This is NOT the legacy
Android JSON backup and does NOT switch the authoritative task source.

## Why SQLite-native export

The editable Rust working copy uses canonical SQLite, possibly with
write-ahead logging (WAL). Copying the live `.sqlite3` file directly can
omit committed changes that still live in its `-wal` file. Consequently
the app uses SQLite's **`VACUUM INTO`** through its Rust JNI module to
create a transactionally consistent, self-contained backup. No full task
payload is passed through WebView or a JavaScript/native object bridge.

## User-initiated workflow

1. Android **Settings → Your data → Export native SQLite backup**.
2. The native Android Activity confirms the user wants an independent
   backup of the experimental *Rust working copy*, distinct from ordinary
   Android task records.
3. The Activity creates a unique, app-private temporary path. Rust
   checks that the source exists, is readable, is schema v3, passes SQLite
   `quick_check`, and has the original archived legacy source.
4. Rust executes `VACUUM INTO ?1` with the new staging destination,
   verifies size (64 MB maximum), reopens the copy read-only, checks
   integrity again, and compares archival source plus active/deleted
   task and dependency counts. Failed exports clean the newly created
   staging file and do not alter source records.
5. Android opens the standard `ACTION_CREATE_DOCUMENT` Storage Access
   Framework picker, with a suggested
   `SHIORI-native-working-backup.sqlite3` filename.
6. Once the user chooses a destination, Kotlin streams the staged file
   through `ContentResolver`, checks the number of bytes copied,
   closes the output, deletes its private staging file, and reports
   success or failure to the user. No broad external storage permission
   or network permission is required.

The exported file retains SQLite tables, indexes, canonical task
revisions, deleted-record tombstones, dependency edges, creation/update
times, and the imported original JSON sidecar. This is a real SQLite
database snapshot, not an approximation of the current UI list.

## Integrity and limitations

**This feature is export-only.** It deliberately does not implement
native restore, merge, repair, promotion or migration. The user must keep
their existing Android JSON backup as well. Successful export confirms a
consistent private SQLite snapshot was created and transferred to the
selected document provider, but it does not independently guarantee
the remote provider's later availability, retention, or continued
integrity. Restore requires a separately reviewed safe import workflow
with format/schema validation, rollback and non-overwriting semantics.

The source copy remains on the device, untouched. Export failures
and cancelled document selection do not modify original tasks.

The SQLite count/legacy-source verification is a sanity check; it is not
an externally signed authenticity proof. Exports larger than 64 MB are
blocked to avoid unbounded staging/storage usage; proper streaming,
encrypted backup options, and end-to-end restore tests remain future
work.

## Automated coverage

Rust host tests exercise a WAL-mode source, edited/active/deleted tasks,
canonical dependencies, original imported JSON preservation, SQLite
integrity, backing-file survival and refusal to overwrite an existing
destination. Android Gradle CI must build the new JNI symbol on each
target ABI. Browser-origin tests confirm the explicit export action
is available but do not exercise Android's Storage Access Framework.

**Real Android emulator/phone tests remain required** for document
picker availability, cancellation, lifecycle interruption, storage
exhaustion and actual recovered backup validation. This is not
release-ready migration and no draft PR is merged without approval.
