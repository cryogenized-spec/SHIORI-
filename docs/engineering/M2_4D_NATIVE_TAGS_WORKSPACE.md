# M2.4d — native tags, saved views and sorting are authoritative in SQLite

**Status:** Debug-only native canary feature. No production source cutover, automatic merge or migration of native-only edits into the frozen Android WebView store.

## Canonical native commands

The existing allowlisted JNI command bridge remains the only WebView-to-Rust path, with the same request-size, source-selection, serialization and timeout controls.

* `tags_set`: `{op, id, expected_version, tags}` atomically replaces a single task's ordered tags and increments the **canonical task revision** in one SQLite immediate transaction. The old task revision, missing/deleted IDs, duplicate case-insensitive tags, controls, excessive tag count and overlong tag values fail without changing records. Up to 16 tags, each at most 40 characters.
* `workspace_set`: `{op, expected_revision, saved_views?, sort?}` validates and updates native workspace preferences in one SQLite transaction. Revision increases after each accepted change; concurrent/stale requests fail without overwriting newer settings. Saved views must use the original supported five-field schema, with a maximum of 30 entries and unique case-insensitive names. Only supported `focus`, `fifo`, `due`, `priority` ordering modes are accepted.
* `metadata`: returns current ordered tag values, saved views, sort and a positive workspace revision.

**Compatibility:** Native databases created before M2.4d do not have an `android_workspace_revision` table. Read-only metadata inspection treats these original databases as revision 1. Their first explicit workspace write creates the separate revision table transactionally and advances it to 2, without touching their canonical task schema, source archive or existing metadata. Existing untouched migration candidates and their verified native exports retain revision 1.

## UI and source isolation

When the Rust primary is selected, task details include an explicit **Save tags** field. Task tags never go through legacy localStorage. The regular saved-view buttons and sort dropdown dispatch the `workspace_set` command rather than mutating WebView preferences, and refresh their values after a confirmed SQLite write.

When selecting native tasks, the Android UI loads its saved-view list and sort mode from native metadata. When explicitly rolling back, it reloads the original saved views and sort from their preserved WebView localStorage keys. No native tag or workspace edits are merged back automatically.

Android's WebChromeClient is configured to display the trusted bundled page's prompt and confirmation dialogs; without this, a native saved-view name prompt may not appear. No JavaScriptInterface, Internet or external storage permission is introduced.

## Export and recovery fidelity

`export_working_database` now verifies **all canonical task and dependency rows plus ordered native tags, saved views, sort and workspace revision** between source and exported SQLite, not merely record counts and the original legacy JSON manifest. The isolated recovery validator uses the same full-row checks. A mismatch rejects and removes only the newly created incomplete output, never the input source or an existing destination.

## Tests and remaining acceptance

Rust tests exercise modified tags, task revision conflicts, duplicate/invalid tags, missing IDs, source archive preservation, old-database revision compatibility, saved-view/sort revisions, malformed/duplicated views, standalone export and isolated recovery. Android browser-origin tests exercise native command dispatch, UI edits and preservation of legacy preferences after rollback; standard CI builds the debug APK and runs its Android emulator lifecycle job.

**Not yet proved on a physical phone:** soft keyboard with saved-view prompts, direct tag typing, document providers under low storage, task deletions during tag edits, interruption between SQLite commits and process termination. Complete these acceptance checks before declaring the native source production-ready.
