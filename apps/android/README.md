# SHIORI Android offline shell (M2 alpha)

This is an **actual native Android Activity**, deliberately small and self-contained. It serves the **same** responsive SHIORI web UI assets from the APK through a private HTTPS-like WebView origin. It has **no INTERNET permission**, no JavaScript bridge, and blocks outbound navigation.

## Offline behaviour

On Android, `app.js` enters `android-local` mode. It starts with an **empty personal task list** rather than the demonstration fixture. Task creation, edits, completion, deletion, FIFO views and filters are saved only in this device's **WebView DOM storage**. The experience works without a server, Cloudflare, ChatGPT, an account or an Internet connection.

**Architectural limitation:** this is a *native Android shell using an embedded browser storage backend*, **not yet the same Rust/SQLite database** as desktop. The task UI is shared, but storage engines are not; there is no sync between Android and desktop. WebView localStorage is not an adequate long-term backup mechanism. Do not describe this as the finished native Rust client, production backup system, or a distributable release.

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
