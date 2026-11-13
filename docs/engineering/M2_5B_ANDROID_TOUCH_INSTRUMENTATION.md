# M2.5b — Genuine Android WebView touch tests (CI emulator)

**Purpose:** Close the blind spot in M2.4c/M2.5: Android's UIAutomator node dump did not expose SHIORI's New Task button, so the touch-dialog verification was being skipped. The old emulator smoke only proved that the app process launched and survived lifecycle events.

## Test isolation and Android runtime

This change adds a dedicated `androidTest` APK built with AndroidX Test, separate from the actual SHIORI APK. It has no effect on the production/debug application's permissions or offline dependencies. GitHub Actions builds both APKs from one commit, archives the touch test APK separately, and installs them into the **same Android 15 emulator** after checking the application APK's commit-bound evidence manifest.

`WebViewTouchAcceptanceTest.kt` uses Android's `Instrumentation.sendPointerSync` to send real screen-coordinate pointer events to the embedded WebView. It reads element locations using `getBoundingClientRect` and the physical WebView viewport geometry, then sends genuine `ACTION_DOWN`/`ACTION_UP` input. JavaScript is used only to **inspect** the DOM/storage, and to scroll the intended touch target into view. The test does not use `element.click()`, `form.requestSubmit()`, synthetic DOM events, or a mocked native bridge.

Android's first instrumented run exposed a concrete **responsive-viewport issue**: the mobile capture button had a zero-width layout rectangle in the actual WebView. The Activity now enables `WebSettings.useWideViewPort` so its existing `width=device-width` meta tag is respected on phone-sized displays. A separate upfront assertion checks the Android viewport breakpoint and minimum 44-pixel layout width for the mobile capture control, then the tests inject pointer events.

Required scenarios:

1. Open New Task via the mobile plus button, close it via its header X. Repeat with real keyboard typing and the Cancel button. Assert the discarded task never appears in on-device localStorage. Open a third time and dismiss through Android Back (allowing an initial Back to dismiss the soft keyboard).
2. Open a new task, enter a unique title through Android input injection, tap Create with a real pointer event, verify that the offline record is stored. Recreate the actual Android Activity and WebView, then confirm the task loads from on-device storage rather than a test fixture.

A failure, missing test count, or instrumented JUnit error fails the whole emulator job. It no longer treats absence of a UIAutomator accessibility node as sufficient test coverage. The older optional probe can remain as a separate inspection, but successful instrumentation is now **required**.

## Scope and safety

The tests execute on a disposable Android emulator using the legacy offline WebView storage. They do not exercise a physical phone or the opt-in native Rust/SQLite cutover. Native tags, saved-view prompts, SAF provider interruption, low storage, vendor keyboards, stable-signing upgrades, and full rollback integrity still require additional acceptance work.

The production app does not acquire Internet permission, a JavaScript interface, any instrumented-test dependency, or a new data migration. PRs remain draft, and no production release can be approved on emulator evidence alone.
