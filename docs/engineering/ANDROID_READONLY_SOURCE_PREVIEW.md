# M2: Reversible Android native-source preview

**Status: opt-in, read-only, and non-authoritative.** This milestone does
**not** make Rust/SQLite the live Android task store, migrate original tasks,
or silently synchronize two databases.

## User experience

In Android Settings, initialize the separate Rust task working copy with
explicit confirmation (as in PR #12), then open its native task workspace
(as in PR #13). Select **Preview Rust tasks in normal task layout ·
read-only**.

The preview reuses the existing SHIORI Inbox task-row layout, rather than
temporary Kotlin dialogs, but is visually separated from editable tasks.
Native records are projected only into this display: the existing `tasks`
array is never replaced or merged with Rust results. Native rows contain
no complete, edit, detail, drag or delete controls. The global add action
and keyboard shortcut are disabled while the preview is active.

**Return to Android tasks** restores the legacy task view immediately.
Navigating away from Inbox also ends the preview. The selected data
source is **ephemeral** and is deliberately not persisted in preferences or
backups: restarting the app always opens the original Android task source.

The native task panel in Settings (PR #13) can still create and edit
records in its **separate** working copy. Those edits are not shown in the
regular Android task list. The read-only Inbox preview gives a familiar
layout for comparing these records without promoting them.

## Data-protection boundaries

- No writes to original WebView `localStorage` task records are performed
  by the source preview.
- The preview never sends a native mutation command: its only Rust
  operation is a fresh `list` call.
- Existing legacy editor, status, deletion, drag-and-drop, task creation
  and save entrypoints have explicit guards while the preview is active.
- Existing JSON export continues to export **original Android tasks**,
  not native preview records. This is deliberate: the native working
  copy still needs its own independent backup/export before cutover.
- The underlying Kotlin bridge selects the fixed private native working
  database path. No network or generic JS/JNI object interface is added.
- Native list responses are capped at 50 records by PR #12. If the reported
  total exceeds the response length, switching to the normal task layout
  is refused, with an explicit pagination warning. No partial list may
  masquerade as a complete task-source migration.
- HTML text from Rust is escaped before rendering.
- The preview uses the current search/priority/sort controls against the
  copied native records in memory; it does not mutate original tasks or
  saved views.

## Verification

Browser-origin regression tests emulate the Kotlin take/complete
handshake and confirm the source switch, non-editable rows, add shortcut
guard, return to legacy records, original storage unchanged, rejection of
truncated lists and lack of persisted source selection across reloads.

This test is **not** Android emulator or physical-device verification. Do
not claim production readiness from a successful GitHub Actions build.
The preview remains gated on the native working-copy feature.

## Remaining M2 cutover gates

1. Native working-copy pagination and reliable full-record export/backup,
   including deletion records, metadata and ancillary legacy fields.
2. Pre-cutover snapshot, authenticity/integrity checks, accurate field
   mapping, external backup and explicit irreversible-operation review.
3. Physical Android process-death, app-update, low-storage, WebView
   bridge and rollback testing, including the original task-creation
   cancel/back issue.
4. A reversible **typed native source adapter** for the normal editing
   interface, with explicit migration and revision conflict handling.
5. Offline notifications, richer filtering, accessibility and release
   hardening.

All stacked PRs remain drafts until explicit approval to merge.
