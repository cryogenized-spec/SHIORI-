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

## Read-only staged-migration audit (next M2 increment)

Once a preview has been staged, **Settings → Your data → Audit staged Rust preview**
performs an explicit on-demand audit. This action does **not** create a shadow
database if one is missing, update staged tasks, overwrite the separate safety
vault, or mutate WebView localStorage.

The native Rust audit opens SQLite with read-only flags, runs an integrity
check, verifies the expected schema version, loads the original archived
backup, and compares canonical row count and task fields: IDs, titles, notes,
projects, priorities, statuses, due dates, effort, assignments, revisions,
no tombstones and reconstructable timestamps. Tags and saved views remain
preserved in the archived source JSON but are not yet canonical tables.

The current phone export is compared with the original source, ignoring only
the changing export timestamp. Results distinguish:

- **Missing preview:** a migration preview has not been staged.
- **Verified and current:** canonical fields agree; the phone still matches.
- **Verified but stale:** canonical data is internally sound, but live phone
  data changed since staging. **Do not activate this copy.**
- **Audit failed:** the database is invalid, missing data or inconsistent
  with the archived source. Existing WebView tasks remain unchanged.

Old backups without export/created timestamps can have inferred historical
times that cannot be reconstructed; the audit explicitly reports how many
timestamp fields were not fully verifiable.

**Not a migration cutover, a restore method, or a release-gate pass.** The
audit does not repair a stale or corrupt shadow file. Future promotion
requires a separate, reviewed staging/rollback path. Physical-device
verification for JNI, corrupted storage and process death is still needed.

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
