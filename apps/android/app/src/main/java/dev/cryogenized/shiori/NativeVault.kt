package dev.cryogenized.shiori

/**
 * Narrow Kotlin-to-Rust JNI entrypoint for the app-private, crash-safe SQLite
 * safety copy. It is NEVER injected into WebView JavaScript.
 *
 * Task field validation and snapshot persistence live in the Rust cdylib.
 * The WebView app's previous localStorage remains untouched during migration.
 */
internal object NativeVault {
    init {
        System.loadLibrary("shiori_android_native")
    }

    external fun loadSnapshot(databasePath: String): String?
    external fun storeSnapshot(databasePath: String, backupJson: String): Boolean
}
