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

## 14 November — native modal autofocus and two-pass repeatability

A later two-round emulator suite exposed intermittent lost touchscreen taps:
on the second instrumented pass an X-button touch could coincide with the
automatic Android IME transition, while another run failed to reopen New Task
after cancelling. The root issue was not established by DOM `elementFromPoint`
alone: JavaScript can report a clickable target while Android is still
reconfiguring the keyboard/window.

For real Android host sessions (`android-local` with
`shioriNativeBridgeEnabled===true`), creating or editing a task **no longer
automatically focuses the input on dialog opening**. This avoids bringing up
the keyboard before the user intentionally taps the text box. Desktop and
browser-only prototype flows retain autofocus. Users can still tap the task
title to begin typing; native Cancel/Back continue to request Android IME
dismissal.

The Android instrumentation now waits for the trusted native bridge before
testing modal interactions, checks that opening a task does not automatically
summon the keyboard, verifies keyboard dismissal after Cancel and reruns the
full two-test pointer suite twice without clearing app data. These checks
are **not equivalent to physical-handset acceptance**. Keep this branch
blocked until the current exact-head Android emulator workflow passes.

## Android 15 foreground-window recovery experiment — 18 November 2026

Issue [#65](https://github.com/cryogenized-spec/SHIORI-/issues/65) reappeared in documentation-only PR #78's Android emulator run: both native tests timed out before any gesture with a visible, attached, 1080 × 2138 WebView reporting `hasWindowFocus() == false`. APK/native compilation and the other quality checks passed. The preceding synchronization PRs had each passed the same real-touch suite, confirming this is intermittent startup state, not evidence of a synchronization regression.

The instrumentation test now gives Android three seconds to hand over window focus normally. Only if focus remains absent does it use `UiAutomation.executeShellCommand("am start -W -f 0x30000000 -n dev.cryogenized.shiori/.MainActivity")` to bring the existing app task to the foreground, without clearing the activity data or injecting a task gesture. It then captures the WebView again and still requires normal window focus, correct mobile viewport geometry, genuine touchscreen DOWN/UP input, modal behavior, offline persistence and Activity recreation. The test also reports decor-window and decor-view focus separately if it fails. It does **not** use JavaScript clicks, skip assertions, or implement a retry loop for failed gestures. This is a CI-only focus-restoration experiment, not a production-application change or proof that the Android problem is fully resolved. A real handset remains an acceptance requirement.

### Follow-up from the first PR #79 emulator run

The native app and APK passed, but the emulator suite failed after successfully opening the New Task modal. A real tap at the header X target was accepted by the automation input injector and matched the DOM hit-test, yet the modal stayed open. The initial startup focus was not the remaining failure in this run.

The experiment now also verifies Android window focus before **each** touch, not only the initial New Task button. A test-only WebView `OnTouchListener` returns `false` (never consumes input) and records the native DOWN/UP sequence; after `UiAutomation.injectInputEvent`, the assertions require matching actual WebView dispatch timestamps. A failed tap is **never retried**. These diagnostics distinguish a missing native input delivery from a WebView handler failure without claiming either is fixed. The actual app is unchanged.

### Android 15 WindowManager handoff follow-up

After PR #79 merged with a green emulator run, the same startup failure recurred on PR #81's first Android check: the WebView was attached and shown at 1080 × 2138 pixels, while both the WebView and its decor root reported **no input focus**. The ordinary `am start -W` foreground selection was insufficient in that run; PR #81 passed the unmodified touch checks on a later isolated retry. This keeps [issue #65](https://github.com/cryogenized-spec/SHIORI-/issues/65) open.

The CI-only focus restoration now waits three seconds for normal focus, reselects the existing SHIORI app task and waits four seconds, then performs at most **one** system-level Home-to-app relaunch if focus is still absent. It requires actual native root/WebView focus before the test proceeds. If WindowManager still refuses it, the test fails with input-owner diagnostics rather than injecting a gesture into the wrong window. This is not a DOM click, a retry of a failed WebView touch, a production UI change or evidence that physical Android devices are reliable. All real DOWN/UP dispatch, modal, IME and offline persistence assertions remain.

**Acceptance:** Keep issue #65 open even if this experiment passes once; record multiple independent Android emulator runs and a physical-handset touch/IME lifecycle check before considering the focus defect resolved. A green retry is not proof that intermittent focus loss has been eliminated.

### Genuine touch-up without a synthesized click (issue #65, 19 November 2026)

A real Android 15 emulator run for private-backup PR #98 reached `.mobile-fab` with native touchscreen input, had genuine DOM `pointerdown`, `touchstart`, `pointerup`, `touchend`, hit-testable target bounds, and a focused WebView, yet Chromium generated **no `click`** and the New Task modal did not open. This is not a missing document event listener or an Android view-focus failure.

The fallback binds only persistent New Task buttons. It accepts an actual **trusted primary touch pointer release** if that pointer pressed the same enabled button, finished within 650 ms, moved no more than 14 CSS pixels, and remained inside the current button bounds. `pointercancel` clears the pending gesture. It opens the modal once and suppresses the subsequent synthesized click if Chromium does produce it. The normal direct click handler remains for mouse, keyboard, accessibility and browser tests. Synthetic `dispatchEvent` pointers with `isTrusted=false` do not qualify. No app-side `click()`, automatic touch retry, automatic task creation or global pointer instrumentation is introduced.

Run the existing Android 15 tests with native `UiAutomation.injectInputEvent`, and **keep issue #65 open** until repeated emulator and physical-device runs confirm reliability and drag/cancel safety. The existence of one successful run does not prove the issue resolved.

### Genuine Android pointer class and event interception (19 November 2026)

Another Android 15 emulator lifecycle run on S9 PR #103 received native DOWN/UP and DOM `pointerdown/pointerup/touchstart/touchend` on the visible New Task FAB yet did not produce a click or open the modal. The existing fallback accepted only `pointerType==='touch'` on **bubbling** listeners; actual pointer classes and handler rejection reasons were not being recorded.

The FAB now accepts any **trusted primary pointer press/release** within the same enabled button (mouse pointer requires primary left button). It attaches the two handlers in the **capture phase**, so nested SVG event cancellation cannot prevent delivery, and retains strict bounds, duration, movement, pointer identity and cancellation checks. Its post-gesture synthesized click is deduplicated. Synthetic JavaScript `dispatchEvent` remains untrusted and cannot trigger the fallback. No task creation is simulated or automatically retried.

The CI-only DOM event telemetry records `pointerType`, `isTrusted`, `isPrimary`, button, target and the FAB handler's last decision, and is printed **only when a genuine-touch test fails**. No user task data or credentials are included. This supports a root-cause diagnosis if even the capture-phase fallback fails. Physical-device and repeat-emulator validation are still required before closing issue #65.
