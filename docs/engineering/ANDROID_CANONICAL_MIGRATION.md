# M2 Android → canonical Rust database: shadow migration

**Status:** experimental, user-initiated, non-destructive preview. This does **not**
switch Android task CRUD to the canonical Rust engine. SHIORI Android still uses
WebView localStorage for live tasks, and the Rust private snapshot vault remains
an independent safety copy.

## Why stage a shadow copy first?

Android v0.1.2–0.1.3 stores task IDs such as `u170000...`, task states such as
`progress`, user-interface tags and saved views in a JSON document. Canonical
SHIORI uses Rust `Task` records, `in_progress` status, versioned SQLite
schema and tombstones. Simply copying JSON fields or switching databases
would lose information.

The new **Settings → Your data → Stage Rust migration preview** action uses
Android's internal `shiori-vault://stage` navigation, intercepted by Kotlin.
The user sees a confirmation dialog. Kotlin obtains the current snapshot using
the bundled page's existing export function, then calls the Rust JNI converter
on a serialized I/O worker.

The converter stages records in the **separate private file**
`filesDir/shiori-canonical-preview.sqlite3`. It uses
`SqliteStore::open` and the *canonical* SQLite schema, not a second task
persistence design. The transaction inserts every converted task **and**
archives the unmodified source JSON in `legacy_shadow_source`. The transaction
is atomic. The stage rejects a nonempty target, duplicate IDs and a different
previous import instead of overwriting tasks. Repeated requests with the same
content are idempotent even if only the export timestamp changes.

## Supported field mappings

| Android backup | Canonical Rust task |
| --- | --- |
| `id` | Preserved **as-is**, including legacy `u...` IDs |
| `title`, `description`, `project` | Title, notes, project |
| `priority` | Matching Rust `Priority` |
| `todo`, `progress`, `done` | `Todo`, `InProgress`, `Done` |
| `due` | `NaiveDate`, without timezone conversion |
| `mins`, `assigneeId`, `version` | Estimate, assignee, revision |
| `createdAt`, `updatedAt` | RFC3339 UTC timestamps when present |
| `completedAt` | Completion time when present; inferred from last update otherwise |
| `tags`, `saved_views`, `sort`, extra fields | Preserved verbatim in archived JSON sidecar |

If timestamps are missing, the importer explicitly counts inferred values in
its report and derives them from the original export timestamp, or the created
timestamp when appropriate. An invalid supplied timestamp is rejected rather
than silently rewritten.

**Important limitation:** the original Android app hard-deletes tasks from its
localStorage array. Records already deleted *before the snapshot was exported*
do not exist in the source. This migration cannot reconstruct them or pretend
that historical deletion tombstones are available. Future native deletion must
write canonical tombstones.

## Safety and rollback

- No changes to the existing WebView records, Rust safety vault or desktop DB.
- Staging cannot proceed if the shadow DB already contains unrelated tasks.
- Existing shadow DB is never overwritten with a different source snapshot.
- Invalid dates/revisions or a SQL insertion failure cannot partially stage
  tasks; read-back verifies identity, fields and preserved source.
- User's manual **Export JSON backup** remains the independent backup route.
- The app does **not** switch to the shadow database or silently clear
  localStorage. It provides no automatic rollback of a future authoritative
  migration; that belongs in a separately reviewed change.
- Success indicates conversion/storage verified by code, not validation on a
  real Android device. Physical-device testing of JNI and lifecycle operations
  is still required.

## M2 exit work remaining

1. Test preview staging and recovery on an actual Android device, including
   process death, storage exhaustion and incompatible/corrupt databases.
2. Define a stable Rust-native typed transport and migrate live CRUD only after
   a verified, reversible source-to-target migration.
3. Preserve local filters, tags and future deletion history as canonical
   supported entities rather than relying indefinitely on archived JSON.
4. Add dependable native notifications and instrumented Android tests.
5. Revisit static web UI architecture (Vite + React or equivalent) once the
   persistence contract is stable; Rust should remain the shared task engine.

**M2 is not formally closed by this shadow migration.**
