# M2.4b — interrupted Android canary cutover recovery

**Experimental debug APK only.** This is an opt-in, non-destructive resume operation. It does not merge, delete or reset a task database, and is not a production Android migration.

## The failure being addressed

The normal M2.3 source transition proceeds in phases: verify a canonical migration candidate → save a separate legacy rollback vault → create a verified native primary SQLite copy → set the Android native-source preference. Android process termination, a force-stop, disk exhaustion, or a failed native copy can interrupt the operation after a file was committed but **before** the source preference changed. Previously, a subsequent normal activation refused these existing files and left the user without a guided resume path.

The original WebView task list remains authoritative until the final preference commit. The new recovery never changes that fact silently.

## Explicit recovery procedure

From **Settings → Verify and resume interrupted cutover** (shown only to debuggable APKs), Android displays a confirmation explaining the risks. After approval, Kotlin freezes legacy task edits and captures a fresh source JSON export.

Rust's new `inspectInterruptedCanary` JNI entrypoint runs **read-only** and refuses to create a missing candidate. It audits the existing canonical migration candidate against the current Android source, including task revisions, dates, notes, ordered tags, saved views and sort mode. Unknown fields or changed source records block recovery. If a rollback vault already exists, it must match both the candidate and live source. If a native primary already exists, Rust must verify its full SQLite integrity, schema, foreign keys, original archive, ordered task/dependency rows and independent metadata against the candidate. Edited or corrupt native databases are preserved and **rejected**, never reset.

Only stages proved to be **missing** are created, in this order:

1. Missing private legacy rollback vault → write a new safety snapshot, read it back and re-inspect.
2. Missing native primary → export from the existing validated candidate to a **new** private temporary SQLite file, verify, atomically rename to the unused primary path and re-inspect.
3. After a final fully passing read-only inspection, persist Android's `selected=true` source preference and ask the WebView to load the native source.

An existing file is never overwritten or deleted by the recovery action. On failure, the original legacy task store remains active, UI edits unfreeze, and all existing artifacts remain available for manual investigation. Android also guards activation, resume and rollback behind a single UI-thread transition lock; a duplicate action cannot unfreeze legacy writes or interrupt another migration audit. The lock is released only after the trusted WebView receives the activation, abort or rollback notification. An in-flight temporary export created by the current attempt is the only file eligible for automatic cleanup. A crash after a completed primary but before preference commit can be resumed without recreating or replacing the primary.

Once a native canary has been edited and later rolled back, it deliberately **cannot** be silently resumed from an edited primary; that database may contain divergent work. Export it separately before adopting any future migration policy.

## Tests and device verification

Host Rust regression cases: no candidate ⇒ no new files, candidate-only ⇒ two missing stages, candidate+vault ⇒ one missing stage, fully verified copies ⇒ ready, edited primary ⇒ refuse, corrupt vault ⇒ refuse and preserve bytes, stale source ⇒ refuse.

Browser-origin CI also verifies that the recovery control is absent for non-debug app mode, and present only after Android enables the debug feature flag. CI checks the new JNI symbol in every packaged Android ABI.

On a **disposable phone/test profile**, test interruptions at each phase. Compare before/after hashes of legacy WebView content and private SQLite sources; force-stop after candidate staging, after rollback-vault creation, after native export/rename, and after preference commit. Resume only from a validated candidate. Test low storage, repeated attempts, malformed primary, native edits made after a previous activation, Android Back and rotation. Confirm that the old task list is still active on failure, native-only edited records are never overwritten, and the final source change is user-approved. A successful emulator or GitHub Actions run is **not** evidence of physical-phone validation.

## Remaining M2.4 gates

Native tag/saved-view editing, Android instrumented document-provider scenarios, interruptions between OS file operations, deterministic recovery after repeated failed resumes, and on-device lifecycle validation are still outstanding. Production cutover remains disabled. Do not merge the stacked draft PRs to `main` without explicit approval.
