# M2.5b — Genuine Android WebView touch tests (CI emulator)

**Purpose:** Close the blind spot in M2.4c/M2.5: Android's UIAutomator node dump did not expose SHIORI's New Task button, so the touch-dialog verification was being skipped. The old emulator smoke only proved that the app process launched and survived lifecycle events.

## Test isolation and Android runtime

This change adds a dedicated `androidTest` APK built with AndroidX Test, separate from the actual SHIORI APK. It has no effect on the production/debug application's permissions or offline dependencies. GitHub Actions builds both APKs from one commit, archives the touch test APK separately, and installs them into the **same Android 15 emulator** after checking the application APK's commit-bound evidence manifest.

`WebViewTouchAcceptanceTest.kt` uses Android's `UiAutomation.injectInputEvent` to send real screen-coordinate pointer events to the embedded WebView. It reads element locations using `getBoundingClientRect` and the physical WebView viewport geometry, then sends genuine `ACTION_DOWN`/`ACTION_UP` input. JavaScript is used only to **inspect** the DOM/storage, and to scroll the intended touch target into view. The test does not use `element.click()`, `form.requestSubmit()`, synthetic DOM events, or a mocked native bridge.

The first instrumented run correctly exposed a **test-orientation issue**: the preceding lifecycle test left the emulator in landscape (851 × 393 CSS pixels), where the responsive stylesheet intentionally hides the mobile FAB. The native smoke now uses Android 15's WindowManager `user-rotation lock 0` command to set portrait explicitly before the touch tests. The Activity also enables `WebSettings.useWideViewPort` as a viewport compatibility safeguard, but the landscape measurement did not prove this setting was the underlying bug. The new upfront assertion checks that the emulator is actually at the mobile breakpoint and the FAB has at least 44 CSS pixels of width before touch injection.

Required scenarios:

1. Open New Task via the mobile plus button, close it via its header X. Repeat with real keyboard typing and the Cancel button. Assert the discarded task never appears in on-device localStorage. Open a third time and dismiss through Android Back (allowing an initial Back to dismiss the soft keyboard).
2. Open a new task, enter a unique title through Android input injection, tap Create with a real pointer event, verify that the offline record is stored. Recreate the actual Android Activity and WebView, then confirm the task loads from on-device storage rather than a test fixture.

A failure, missing test count, or instrumented JUnit error fails the whole emulator job. It no longer treats absence of a UIAutomator accessibility node as sufficient test coverage. The older optional probe can remain as a separate inspection, but successful instrumentation is now **required**.

## Scope and safety

The tests execute on a disposable Android emulator using the legacy offline WebView storage. They do not exercise a physical phone or the opt-in native Rust/SQLite cutover. Native tags, saved-view prompts, SAF provider interruption, low storage, vendor keyboards, stable-signing upgrades, and full rollback integrity still require additional acceptance work.

The production app does not acquire Internet permission, a JavaScript interface, any instrumented-test dependency, or a new data migration. PRs remain draft, and no production release can be approved on emulator evidence alone.

Android 15's UID-targeted `Instrumentation.sendPointerSync` rejected WebView screen taps with `Targeted input event injection ... not directed at a window owned by uid`. The instrumentation test now uses `UiAutomation.injectInputEvent`, with an explicit successful-injection assertion for both DOWN and UP, so this input-permission issue cannot be confused with a passing UI test. This does not grant the app itself any input-injection capability; it is confined to the separate test APK.


## Android 15 IME obstruction, 14 November 2026

At commit `f597fc3`, both instrumented tests still failed after successful
native keyboard entry: tapping Cancel and Create left the modal open. The
diagnostic reported a full-height `1080x2340` WebView while
`rootWindowInsets.isVisible(ime)` was true. The action target's CSS center
was at screen y≈1801, consistent with being covered by the Android keyboard.
The DOM's `elementFromPoint` returned the button, because that query does not
account for OS-level keyboard windows.

To address the application bug rather than bypass the check, the Activity
now hosts its WebView in an inset-aware `FrameLayout`. On Android 11+ it
applies system-bar/display-cutout insets and the larger of the bottom system
inset and IME inset to the container. It forwards a *zeroed, non-consumed*
insets object to WebView, preventing duplicate insets and stale keyboard
spacing when the keyboard hides. Android 10 and older retain the existing
`adjustResize` behaviour. This follows Android's WebView inset guidance.
The instrumentation now rejects coordinates under the reported keyboard
top **before** injecting real pointer events.

This patch is not proof of correction on its own: both genuine injected
touch tests must pass in the same emulator job; a successful APK build,
DOM hit test or JavaScript-only action is insufficient. Device-specific
keyboard behaviour and physical-handset sign-off remain unverified.

## Reopen-after-Cancel keyboard regression

An integration run of M2.5b revealed a second Android 15 edge case even after both tests had once passed: Cancel closed the HTML dialog but the Android keyboard stayed visible. The next injected tap on the mobile New Task button was accepted as a screen touch but failed to reopen the form. The recorded Android IME visibility was true, even while `elementFromPoint` reported that the button itself was unobscured in the DOM.

The bundled Android web app now requests `shiori-ui://dismiss-ime` when either task modal is dismissed. MainActivity handles this **app-internal, main-frame-only** command by calling Android's `InputMethodManager.hideSoftInputFromWindow`; it does not expose a JavaScript interface or add Android permissions. This is in addition to blurring the HTML input and restoring focus to the opening control. Non-Android browser sessions do not send the command.

The instrumentation requires the real keyboard to become invisible after Cancel **before** tapping New Task for the Back-navigation scenario. This gate still requires both actual pointer-event tests to pass, including task persistence after Android Activity recreation. Passing general quality checks without the emulator job is insufficient.
