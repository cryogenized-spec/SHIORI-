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
    /** A read-only migration trial for WebView users, not the active store. */
    external fun stageLegacyBackup(shadowDatabasePath: String, backupJson: String): String?
    /** Read-only audit; reports whether the staged shadow still matches live tasks. */
    external fun auditLegacyShadow(shadowDatabasePath: String, backupJson: String): String?
    /** Create an editable *separate* task database; never switches live tasks. */
    external fun initializeWorkingCopy(workingDatabasePath: String, backupJson: String): String?
    /** Revision-checked Rust task commands, only called by Kotlin dialogs. */
    external fun workingCopyRequest(workingDatabasePath: String, requestJson: String): String?
    /** Export-only, verified SQLite snapshot into a NEW private staging path. */
    external fun exportWorkingCopy(workingDatabasePath: String, stagingPath: String): String?
}
