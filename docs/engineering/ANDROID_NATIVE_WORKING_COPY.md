# M2: Android experimental Rust task working copy

**Status:** isolated, opt-in engineering preview. **Not** the authoritative
Android task store, a synchronization engine or a production release.

The native Rust/SQLite task working copy proves that the Android APK can use
the same shiori-core / shiori-storage task-domain operations as the desktop
CLI rather than reimplementing task rules in Kotlin or JavaScript.

## How it is opened

In the Android shell, open **Settings → Your data → Open native Rust task
workspace**. On first use the native Android Activity asks for explicit
consent before archiving the current Android WebView task snapshot and
importing its canonical Task rows into a third app-private file:

- Live WebView tasks: embedded WebView localStorage, unchanged.
- Native safety vault: `filesDir/shiori-rust-snapshot.sqlite3`, unchanged.
- Immutable audit shadow: `filesDir/shiori-canonical-preview.sqlite3`,
  unchanged and still auditable.
- **Experimental editable copy:** `filesDir/shiori-native-working-v1.sqlite3`.

The working copy is created once using the existing atomic
`stage_legacy_backup` conversion. The original source JSON is archived in
the same transaction as the canonical tasks. On future opens an existing
working copy is **not** replaced with a more recent WebView snapshot: that
would silently erase native edits. Source changes never auto-sync.

All native editing is done through Android dialogs on the Activity side,
calling narrow Kotlin JNI methods. **No `addJavascriptInterface` is
exposed.** The embedded web page only uses a fixed, app-internal custom
scheme to request opening the workspace; it does not send arbitrary
commands to native code.

## Operations

The versioned native command protocol, `shiori-native-working-v1`,
currently exposes:

| Operation | Canonical implementation | Protection |
| --- | --- | --- |
| `list` | `SqliteStore::list` | 50-item display limit; total count reported |
| `create` | `Task::new` and `SqliteStore::insert` | field validation |
| `rename` | `SqliteStore::edit_if_version` | revision precondition |
| `status` | `SqliteStore::set_status_if_version` | revision precondition |
| `delete` | `SqliteStore::delete_if_version` | revision precondition; tombstone preserved |

The editor is deliberately narrow: title editing, completion/reopening,
creation in the "Native preview" project, and soft deletion. Editing
projects, priorities, due dates, estimates and assignments from the native
dialog is not yet available. The core store preserves those values during
the seed import; future native UI will use typed patches and version
preconditions.

The native JNI request payload is size-bounded; the file path is supplied
by the trusted Kotlin Activity and cannot be selected by WebView content.
All Rust requests are executed on the Activity's dedicated serial
executor, away from the UI thread. A missing working copy cannot be
silently initialized by a read or mutation.

## What this increment proves

- Existing legacy Android tasks can be copied into Rust's canonical model
  without changing their identity or affecting the original source.
- New native tasks persist in SQLite across requests/reopening the file.
- A rename, completion/reopening and soft deletion use canonical domain
  operations, not a duplicate Kotlin persistence design.
- Stale revisions fail closed rather than overwriting newer edits.
- Deletion creates a canonical tombstone, instead of removing history.
- Bad payloads and attempts to use an uninitialized working copy are
  rejected; the original archived source is not overwritten.
- Android CI checks each of the exported JNI symbols and builds an APK for
  the supported ABIs.

## Remaining M2 gates

1. **Real Android runtime testing:** install/update continuity, JNI
   initialization, process death, storage exhaustion, damaged SQLite,
   back/gesture handling and dialogs with an on-screen keyboard.
2. **End-to-end UI integration:** stabilize a typed asynchronous
   native-to-WebView task transport before using Rust-backed records in
   the normal task list. Native dialogs are a temporary proof, not the
   final UX.
3. **Durable user migration:** verified pre-cutover backup, explicit
   confirmation, source freshness check, all ancillary data mapped
   (tags, saved views, ordering), a reversible rollback strategy and
   lossless old ID/tombstone handling.
4. **M2 essentials:** native notifications, realistic large-task
   benchmarks, saved-filter parity, offline accessibility testing.
5. **Future sync:** accounts, conflict resolution and remote transport
   belong to M4, not this Android proof.

Do not treat successful CI compilation as evidence of an Android device
runtime pass. Do not merge the stacked draft PRs to main without explicit
approval. Experimental native records are **not** a substitute for
exporting the live Android JSON backup.
