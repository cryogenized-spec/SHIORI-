# M2.2 — field-complete Android → Rust cutover preflight

**Experimental preflight only.** The existing WebView task source remains authoritative; no source selection or write routing changes in this milestone.

## Preservation rules

The current Android JSON backup is staged into a distinct canonical SQLite candidate at `filesDir/shiori-native-cutover-candidate-v1.sqlite3`. All domain fields—task identity, title, description, project, priority, status, due date, estimate, assignment, revision, created/updated/completed times—are checked using the existing canonical migration audit.

The migration now ALSO stores **first-class SQLite metadata** in `android_task_tags` (task/tag/position) and `android_workspace_metadata` (saved views JSON and sort mode). These are transactionally imported together as a separate idempotent SQLite metadata transaction after canonical task import, and the original full JSON source remains archived. If metadata creation fails, cutover readiness remains false; repeated staging can resume without deleting the candidate. Existing tags or metadata are never silently overwritten.

A new parity preflight validates the original archived source against the **current** WebView export (ignoring the regenerated `exported_at` value), compares all canonical fields, and verifies the saved-view array, sort preference and task-tag ordering against their native SQLite representations. It reports task/tag/view counts, reconstructed timestamp fields, whether the source still matches, and unsupported future fields. Any unexpected root/task/saved-view keys fail readiness; they remain preserved in the source archive but are NOT silently described as editable native fields.

## Android workflow

Settings → **Verify migration field parity** runs a typed, user-initiated JNI audit and shows whether cutover is blocked or the candidate is ready. It does not overwrite the WebView task array, native working-copy DB, native safety vault, immutable migration shadow, or isolated recovered backup.

If the original Android task source changes after staging, the fixed candidate path is NOT silently rewritten. The preflight says the source has drifted and refuses readiness. Candidate discard/reset requires a future explicit, reviewed operation.

## Gates before cutover

- A passing preflight report is necessary, NOT sufficient.
- Keep an independently saved Android JSON backup and a native SQLite export, and pass real-device document-picker/recovery checks.
- Ensure native read/write UI supports every field users are allowed to edit, including tags and workspace preferences, or disable unsupported edits explicitly.
- Require explicit activation and reversible rollback; do not merge original and native records implicitly.
- No automatic migration or native source switching at startup until a separate opt-in cutover has been approved.

Rust tests cover tags, saved views, time/revision preservation, changes to archived fields, unknown future fields and tampering with native tag/sort metadata. All CI tests run on synthetic data. Physical Android verification is still outstanding.
