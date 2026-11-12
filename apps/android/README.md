# SHIORI Android offline shell (M2 alpha)

This is an **actual native Android Activity**, deliberately small and self-contained. It serves the **same** responsive SHIORI web UI assets from the APK through a private HTTPS-like WebView origin. It has **no INTERNET permission**, no JavaScript bridge, and blocks outbound navigation.

## Mobile navigation and cancellation

The task-capture modal has an explicit X and Cancel button. Android gesture/hardware Back closes the topmost SHIORI modal or drawer before leaving the Activity. Exit controls remain at least 44×44 px and the forms scroll when the on-screen keyboard reduces the available height.

This was corrected in the M2 v0.1.1-dev build after testing real pointer taps on the private Android app-assets origin. Browser-origin tests are not a substitute for physical phone validation.

## Offline behaviour

On Android, `app.js` enters `android-local` mode. It starts with an **empty personal task list** rather than the demonstration fixture. Task creation, edits, completion, deletion, FIFO views and filters are saved only in this device's **WebView DOM storage**. The experience works without a server, Cloudflare, ChatGPT, an account or an Internet connection.

**Architectural limitation:** this is a *native Android shell using an embedded browser storage backend*, **not yet the same Rust/SQLite database** as desktop. The task UI is shared, but storage engines are not; there is no sync between Android and desktop. WebView localStorage is not an adequate long-term backup mechanism. Do not describe this as the finished native Rust client, production backup system, or a distributable release.

## On-device backup and restore (v0.1.2-dev)

In **Settings → Your data**, choose **Export JSON backup**. Android opens the system document picker, where you save the JSON file in a location you control. To restore, select **Restore backup** and choose that file. SHIORI shows a native confirmation that restoration will replace the offline task list; Cancel leaves it unchanged.

The backup includes offline tasks, saved views, and list sorting. Titles and notes are stored **in plain text**, so protect the exported document. Android's Storage Access Framework supplies the chosen file without Internet or broad external-storage permissions. Only the `shiori-android-local-v1` format is accepted; imports are validated before overwriting local data, with a 2 MB native file limit.

**Limitations:** the file pickers still need real-phone testing. Rollback of WebView quota failures is best-effort, not a full database transaction. There is still no background/cloud backup or shared Rust/SQLite storage. Verify that an exported document exists before uninstalling a debug build.

## Open and build

Use Android Studio with JDK 17, Android SDK API 36 and Android Gradle Plugin 9.4. The project is rooted at `apps/android` and uses Gradle 9.9.1. It links `apps/web` as a **packaged asset source** at build time; do not copy a second stale UI.

If you already have Gradle 9.9.1 installed, from the repository root:

```bash
gradle -p apps/android :app:assembleDebug
```

The debug APK will be under `apps/android/app/build/outputs/apk/debug/` after a successful build. Android Studio can import the project directly. The CI Android build uses the official Gradle binary and verifies its SHA-256 before building.

## Security

The Activity only loads bundled app assets via `https://appassets.androidplatform.net` and intercepts all asset reads. Non-local origins are blocked, file/content URI access is disabled, JavaScript popups are disabled, and the manifest requests no network permission. There is no JavaScript-to-native interface.

Security review and Android device tests remain required before publication.

## Unfinished M2 gate

The native shell still needs a **Rust JNI-backed local database**, robust on-device reminders/notifications, backup/export/restore, Android instrumentation testing and identity/permission support for richer collaboration. This alpha does not close those roadmap requirements.
