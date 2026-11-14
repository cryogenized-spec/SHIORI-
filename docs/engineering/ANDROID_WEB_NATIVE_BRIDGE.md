# M2 Android embedded Rust task panel — typed asynchronous bridge

**Status:** opt-in engineering preview, stacked on the native working-copy
increment. This does **not** promote Rust to the normal Android task store,
migrate user records, or introduce network sync or MCP.

## Scope

The Android Settings screen now opens an embedded task panel backed by the
separate app-private `shiori-native-working-v1.sqlite3` database introduced
in the previous increment. The earlier temporary Kotlin task-editing dialogs
are removed. The existing Android WebView task list and its backup/export
formats are unchanged.

First use still requires an explicit Kotlin confirmation to seed a **separate
working copy**. An existing working copy is never overwritten when the
original Android tasks change; it is not an automatic mirror. After
confirmation, the native Activity notifies the embedded UI to load tasks.

The embedded panel supports:

- Reading up to 50 native tasks and showing the total count.
- Creating a native task, renaming one, completing/reopening it, and
  explicitly confirming soft deletion.
- Refreshing the working copy after any successful write.
- Displaying concurrency conflicts and errors rather than treating a stale
  version as a successful update.
- Escaping all returned titles, IDs and projects as untrusted UI strings.
- Keeping the existing normal Android task list entirely unchanged.

## Protocol and trust boundaries

There is **no** `addJavascriptInterface`, network permission, exposed local
HTTP port, or JavaScript access to private filesystem paths.

1. The Kotlin Activity enables the bridge only after its bundled,
   first-party `https://appassets.androidplatform.net/index.html` page
   finishes loading.
2. The UI holds at most one pending request with a monotonically increasing
   request ID. A timeout rejects it, warning the user to refresh before retry.
3. The UI signals `shiori-vault://command`, which the Activity consumes as a
   main-frame navigation. Kotlin checks the current trusted page and pulls
   exactly one request via `evaluateJavascript`.
4. The command has a stable `shiori-native-working-v1` protocol marker,
   numeric request ID and an allowlisted operation (list, create, rename,
   status or delete). Requests are bounded to 16,384 bytes.
5. The trusted Activity selects the *fixed app-private working-copy path*,
   executes the Rust JNI operation on a dedicated serial I/O executor,
   bounds responses to 768,000 bytes and sends the result to the page via
   `evaluateJavascript` with JSON-quoted arguments.
6. The UI verifies the response's request ID and parses a structured
   `{ok: boolean, ...}` response. Unknown or late responses are ignored.
   Stale revisions are rejected by canonical Rust/SQLite operations.

JS command IDs are correlation tokens, **not authentication or encryption**.
The Android bridge is only an app-local transport. It does not claim to
secure an arbitrary or compromised web origin. The Activity must continue
rejecting external navigation and file/content URL loading.

## Operational safeguards

The native preview is **not** joined with the normal task list: the original
WebView `tasks` array, saved views, backups and native safety vault remain
independent. It does not use a background synchronization loop.

Native mutations run through the shared Rust domain and SQLite adapter,
including optimistic revisions, validated fields and tombstones for deletions.
A timeout is *not* proof that a write failed; the UI advises a refresh before
retrying to avoid accidental duplicate creates.

Current native list display is limited to 50 records with total count
reported. Pagination, richer typed task editing, independent native backup,
full accessibility auditing, Android runtime instrumentation, notifications,
and any eventual live-store cutover remain outstanding.

## Validation

- Rust unit and storage tests are inherited from the preceding working-copy
  PR.
- Android Gradle/NDK CI verifies the Rust libraries and compiles the APK.
- Browser-origin regressions simulate the exact one-shot request and
  response functions; they test correlation, read-after-write, HTML
  escaping and isolation from the existing Android localStorage.
- Browser tests are **not** a substitute for running the same path through
  a physical Android WebView. Native lifecycle handling, request delivery
  under no user gesture, activity destruction, Android Back, storage-full
  behaviour and interrupted writes must still be tested on an emulator or
  phone.

No stacked PR should be merged into `main` without explicit approval.
