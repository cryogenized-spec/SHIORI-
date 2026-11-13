# Android M2 — complete, mutation-aware native pagination

**Status:** experimental Rust task-source working copy, not the live Android
task database. This increment removes the previous 50-record *total* limit
for source comparison, without removing the safety boundaries.

## Native `list` request contract

The existing `shiori-native-working-v1` JNI JSON protocol remains in place.
`list` accepts optional nonnegative integer `offset` (default `0`) and,
on continuation pages, a required `snapshot` string from the first result.

Each result carries:
`{ok:true,tasks,total,offset,next_offset,snapshot}`. Pages contain a
maximum of 50 active records in deterministic canonical task-ID order. The
response's `next_offset` is an integer when more records remain or `null`
at the last page. Out-of-range, fractional and negative offsets are rejected.

The snapshot token covers the sorted active task identities, domain
revisions and update timestamps. It is a **non-cryptographic consistency
marker**, not a signature, backup checksum or authentication guarantee.
Changes between native SQLite requests invalidate continuation pages and
require a fresh first-page read.

The native source refuses lists larger than 5,000 tasks. This cap is a
memory/performance safeguard for the current Android preview; it should be
re-evaluated with proper incremental database reads and device benchmarks.
No native write path can be invoked by the read-only preview.

## WebView integration

The Android Settings working-copy panel reads all pages sequentially
through the existing one-at-a-time, bounded Kotlin-to-Rust bridge. The
browser verifies every response's offset, total, token, status, field types
and task IDs, rejecting duplicate IDs, partial pages, inconsistent
continuations or snapshots altered between requests.

Results are **published only after the last page**. On error the old
cached result is cleared; a partially fetched source is never displayed as
complete. Successful source loading does not assign Rust tasks into the
legacy WebView `tasks` array or write to its localStorage, saved views or
backup.

The Settings panel only renders the first 50 native records to avoid a
long screen. The separate **read-only Inbox preview** retains the complete
validated in-memory source, with 50-row Prev/Next controls and
search/priority/sort performed on that source before windowing. Original
Android tasks remain untouched, and exiting/restarting restores the
original task source. No authoritative source cutover is performed.

## Validation

- Rust tests load 123 active records, verify three pages, stable total,
  no missing/duplicate IDs, invalid offsets/token refusal and stale-page
  rejection after an actual task edit.
- Browser-origin regression mocks the native bridge with 61 records,
  verifies two sequential requests, 50/11 row windows, navigation and
  untouched legacy storage, then simulates an interrupted source
  transition and confirms no partial preview is available.
- Android APK compilation still validates the cross-ABI Rust JNI exports,
  network-free shell and Java/Kotlin source; these CI jobs are **not**
  physical-device instrumentation.

## Remaining gates

An independently restorable **native SQLite backup** is next. It must
include edited task records, tombstones, original legacy import archive and
dependencies, and must be exported using a crash-consistent SQLite
mechanism rather than copying a live WAL database file by hand. The
backup's destination needs an explicit Android document picker, validation
and user-visible failure handling.

The final authoritative-store cutover still needs verified snapshots,
field-complete migration, genuine Android device tests, rollback,
native-source editing parity and notifications.
