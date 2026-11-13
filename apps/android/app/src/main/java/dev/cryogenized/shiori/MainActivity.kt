package dev.cryogenized.shiori

import android.app.Activity
import android.app.AlertDialog
import android.util.Log
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.File
import java.util.concurrent.Executors
import android.os.Bundle
import android.os.Build
import android.window.OnBackInvokedCallback
import android.window.OnBackInvokedDispatcher
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.webkit.WebChromeClient
import java.io.ByteArrayInputStream
import java.io.InputStream
import java.nio.file.Files
import java.nio.file.FileAlreadyExistsException

/**
 * Minimal native Android container around the same offline-responsive SHIORI UI.
 * This is an isolated device-local alpha: WebView DOM storage, no HTTP transport,
 * no JavaScript interface, no network permissions, and no fake Rust integration.
 *
 * Future milestone: embed the Rust task domain/persistence via a reviewed JNI
 * boundary before describing the Android client as sharing the SQLite core.
 */
class MainActivity : Activity() {
    private lateinit var webView: WebView
    private var backCallback: OnBackInvokedCallback? = null
    private var pendingExportJson: String? = null
    private var pendingNativeExport: File? = null
    private var nativeRecoveryPending = false
    // UI-thread gate: no second cutover/rollback may abort the first one's
    // freeze while a SQLite I/O transition is pending.
    private var nativeTransitionPending = false
    private val vaultExecutor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Android can recreate an Activity while ACTION_CREATE_DOCUMENT is
        // open. Reuse only an existing private staging file from this app's
        // cache directory; never trust or write a path supplied by a picker.
        pendingNativeExport = savedInstanceState
            ?.getString(STATE_PENDING_NATIVE_EXPORT)
            ?.let(::File)
            ?.takeIf { file ->
                file.name.startsWith("shiori-native-export-") &&
                    file.name.endsWith(".sqlite3") &&
                    file.parentFile?.canonicalFile == cacheDir.canonicalFile &&
                    file.isFile &&
                    file.length() in 1..MAX_NATIVE_EXPORT_BYTES
            }
        nativeRecoveryPending = savedInstanceState
            ?.getBoolean(STATE_RECOVERY_PICKER_PENDING, false) ?: false
        webView = WebView(this)
        // A previously selected native source must be verified BEFORE
        // anything in the legacy task list can be tapped after app restart.
        // Do not flash an editable legacy list while native DB inspection runs.
        webView.visibility = android.view.View.INVISIBLE
        webView.setBackgroundColor(android.graphics.Color.rgb(23, 21, 30))
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            // Respect <meta name="viewport" content="width=device-width">.
            // Android WebView's default wide-viewport setting can leave the
            // mobile FAB hidden behind the desktop-only responsive breakpoint.
            useWideViewPort = true
            allowFileAccess = false
            allowContentAccess = false
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)
            cacheMode = WebSettings.LOAD_DEFAULT
        }

        // A local trusted page uses native JS prompt/confirm for saved-view
        // names and irreversible task actions. Without a WebChromeClient,
        // Android WebView can silently suppress these dialogs.
        webView.webChromeClient = WebChromeClient()
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?
            ): Boolean {
                val uri = request?.url ?: return true
                if (uri.scheme == "shiori-vault") {
                    if (request.isForMainFrame) {
                        when (uri.host) {
                            "sync" -> persistVaultCopy(false)
                            "save" -> persistVaultCopy(true)
                            "recover" -> recoverVaultCopy()
                            "stage" -> confirmCanonicalShadowStage()
                            "audit" -> auditCanonicalShadow()
                            "working" -> openOrCreateWorkingCopy()
                            "command" -> receiveNativeWorkingCommand()
                            "native-export" -> beginNativeDatabaseExport()
                            "native-recover" -> beginIsolatedDatabaseRecovery()
                            "native-inspect" -> inspectIsolatedRecovery()
                            "migration-parity" -> auditNativeMigrationParity()
                            "native-activate" -> beginGuardedNativeCanary()
                            "native-rollback" -> rollbackNativeCanary()
                            "native-resume" -> beginResumeInterruptedCanary()
                        }
                    }
                    return true
                }
                if (uri.scheme == "shiori-backup") {
                    if (request.isForMainFrame) {
                        when (uri.host) {
                            "export" -> beginExport()
                            "import" -> beginImport()
                        }
                    }
                    return true
                }
                return uri.scheme != "https" || uri.host != HOST
            }

            override fun shouldInterceptRequest(
                view: WebView?,
                request: WebResourceRequest?
            ): WebResourceResponse {
                val uri = request?.url ?: return blocked()
                if (uri.scheme != "https" || uri.host != HOST ||
                    request.method != "GET"
                ) {
                    return blocked()
                }

                val decoded = android.net.Uri.decode(uri.encodedPath.orEmpty())
                val resource = decoded.trimStart('/').ifEmpty { "index.html" }
                // No file or content URI access, traversal or external origin.
                if (resource.startsWith('.') || resource.contains("..") ||
                    resource.contains('\\') || resource.contains(':')
                ) {
                    return blocked()
                }

                return try {
                    assetResponse(resource, assets.open(resource))
                } catch (_: java.io.IOException) {
                    WebResourceResponse(
                        "text/plain", "UTF-8", 404, "Not Found",
                        mapOf("Cache-Control" to "no-store"),
                        ByteArrayInputStream(ByteArray(0))
                    )
                }
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                if (url != "https://$HOST/index.html") return
                // The bridge only becomes available for the bundled trusted page.
                // No addJavascriptInterface, network endpoint or arbitrary path.
                webView.evaluateJavascript("window.shioriNativeBridgeEnabled=true", null)
                if (isDebugCanaryAllowed()) {
                    webView.evaluateJavascript(
                        "window.shioriNativeDebugCanaryAvailable=true", null
                    )
                }
                if (isNativeCanarySelected()) {
                    vaultExecutor.execute {
                        val inspected = runCatching {
                            if (!isDebugCanaryAllowed()) null
                            else NativeVault.inspectRecoveredCopy(primaryPath())
                        }.getOrNull()
                        runOnUiThread {
                            if (!isFinishing && !isDestroyed) {
                                webView.evaluateJavascript(
                                    if (inspected != null) "window.shioriNativeActivate()"
                                    else "window.shioriNativeUnavailable()"
                                ) {
                                    if (!isFinishing && !isDestroyed) {
                                        webView.visibility = android.view.View.VISIBLE
                                    }
                                }
                            }
                        }
                    }
                } else {
                    webView.visibility = android.view.View.VISIBLE
                }
                // Read the native vault before creating the initial copy.
                // Never overwrite an older snapshot merely because WebView
                // happens to start with an empty/missing localStorage store.
                vaultExecutor.execute {
                    val result = runCatching { NativeVault.loadSnapshot(vaultPath()) }
                    if (result.isFailure) {
                        Log.w("SHIORI", "Native vault unavailable", result.exceptionOrNull())
                        return@execute
                    }
                    runOnUiThread {
                        if (!isFinishing && !isDestroyed) {
                            webView.evaluateJavascript(
                                "window.shioriNativeVaultEnabled=true", null
                            )
                            if (result.getOrNull() == null) persistVaultCopy(false)
                        }
                    }
                }
            }
        }

        setContentView(webView)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            val callback = OnBackInvokedCallback { navigateBack() }
            onBackInvokedDispatcher.registerOnBackInvokedCallback(
                OnBackInvokedDispatcher.PRIORITY_DEFAULT, callback
            )
            backCallback = callback
        }
        webView.loadUrl("https://$HOST/index.html")
    }

    private fun assetResponse(path: String, stream: InputStream): WebResourceResponse {
        val mime = when {
            path.endsWith(".html") -> "text/html"
            path.endsWith(".css") -> "text/css"
            path.endsWith(".js") -> "text/javascript"
            path.endsWith(".webp") -> "image/webp"
            path.endsWith(".png") -> "image/png"
            path.endsWith(".svg") -> "image/svg+xml"
            else -> "application/octet-stream"
        }
        return WebResourceResponse(mime, "UTF-8", 200, "OK", mapOf(
            "X-Content-Type-Options" to "nosniff",
            "Cache-Control" to "no-store",
            "Content-Security-Policy" to
                "default-src 'self'; script-src 'self'; " +
                "style-src 'self' 'unsafe-inline'; img-src 'self' data:; " +
                "connect-src 'none'; frame-ancestors 'none'; form-action 'none'"
        ), stream)
    }

    private fun blocked(): WebResourceResponse = WebResourceResponse(
        "text/plain", "UTF-8", 403, "Forbidden",
        mapOf("Cache-Control" to "no-store"),
        ByteArrayInputStream(ByteArray(0))
    )


    /** Private path is supplied by the native app, never by web content. */
    private fun vaultPath(): String =
        File(filesDir, "shiori-rust-snapshot.sqlite3").absolutePath

    private fun shadowPath(): String =
        File(filesDir, "shiori-canonical-preview.sqlite3").absolutePath

    /** Separate from the live WebView store, vault and immutable audit shadow. */
    private fun workingPath(): String =
        File(filesDir, "shiori-native-working-v1.sqlite3").absolutePath

    /** Restored backups never overwrite the editable Rust working copy. */
    private fun recoveredPath(): String =
        File(filesDir, "shiori-native-recovery-preview-v1.sqlite3").absolutePath

    /** One independent, never automatically overwritten native cutover trial. */
    private fun candidatePath(): String =
        File(filesDir, "shiori-native-cutover-candidate-v1.sqlite3").absolutePath

    /** The debug-only selected Rust source is independent of earlier tests. */
    private fun primaryPath(): String =
        File(filesDir, "shiori-native-primary-canary-v1.sqlite3").absolutePath

    /** Immutable backup of legacy Android JSON immediately before cutover. */
    private fun cutoverRollbackPath(): String =
        File(filesDir, "shiori-legacy-cutover-rollback-v1.sqlite3").absolutePath

    /**
     * File.renameTo() may replace an existing POSIX destination during an
     * Activity recreation race. NIO move without REPLACE_EXISTING refuses a
     * duplicate target instead of silently destroying a prior database.
     */
    private fun installNewPrivateSqlite(staged: File, target: File) {
        if (!staged.isFile || target.exists()) {
            throw IOException("Native SQLite destination already exists or source is missing")
        }
        try {
            Files.move(staged.toPath(), target.toPath())
        } catch (_: FileAlreadyExistsException) {
            throw IOException("Native SQLite destination was created by another operation")
        }
    }

    private fun isDebugCanaryAllowed(): Boolean =
        (applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE) != 0

    private fun isNativeCanarySelected(): Boolean =
        getSharedPreferences("shiori-native-canary", MODE_PRIVATE)
            .getBoolean("selected", false)

    private fun selectNativeCanary(enabled: Boolean): Boolean =
        getSharedPreferences("shiori-native-canary", MODE_PRIVATE).edit()
            .putBoolean("selected", enabled).commit()

    private fun startNativeTransition(): Boolean {
        if (nativeTransitionPending) {
            notifyUser("Another native storage transition is still running")
            return false
        }
        nativeTransitionPending = true
        return true
    }

    private fun finishNativeTransition(script: String) {
        // Release the guard after the trusted WebView has received the
        // source change / abort signal, not before asynchronous JS dispatch.
        webView.evaluateJavascript(script) {
            nativeTransitionPending = false
        }
    }

    /**
     * The bundled page only signals a custom-scheme navigation; Kotlin pulls
     * the current complete snapshot on the UI thread and passes it to Rust on
     * a single I/O worker. There is no addJavascriptInterface.
     */
    private fun persistVaultCopy(showFeedback: Boolean) {
        if (isFinishing || isDestroyed) return
        webView.evaluateJavascript("window.shioriExportBackup()") { result ->
            val snapshot = try {
                val json = JSONArray("[$result]").getString(0)
                if (json.toByteArray(Charsets.UTF_8).size > MAX_BACKUP_BYTES ||
                    JSONObject(json).optString("format") != BACKUP_FORMAT
                ) throw IllegalArgumentException("Not a supported snapshot")
                json
            } catch (_: Exception) {
                if (showFeedback) notifyUser("No valid offline snapshot to save")
                return@evaluateJavascript
            }
            vaultExecutor.execute {
                val saved = runCatching {
                    NativeVault.storeSnapshot(vaultPath(), snapshot)
                }.getOrDefault(false)
                if (!saved) Log.w("SHIORI", "Rust SQLite safety-copy write failed")
                if (showFeedback) {
                    runOnUiThread {
                        if (!isFinishing && !isDestroyed) notifyUser(
                            if (saved) "Native SQLite safety copy saved"
                            else "Native safety copy could not be saved"
                        )
                    }
                }
            }
        }
    }

    /**
     * Explicit migration dry run only: canonical Rust tasks are written to a
     * separate SQLite file, never to the working WebView store. A failure
     * leaves both the browser data and native safety vault unchanged.
     */
    private fun confirmCanonicalShadowStage() {
        AlertDialog.Builder(this)
            .setTitle("Stage a Rust database preview?")
            .setMessage(
                "Create a separate, read-only migration preview using the current " +
                    "offline tasks? SHIORI will not switch task storage or remove " +
                    "your existing records. Export a JSON backup independently."
            )
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Stage preview") { _, _ ->
                stageCanonicalShadow()
            }
            .show()
    }

    private fun stageCanonicalShadow() {
        if (isFinishing || isDestroyed) return
        webView.evaluateJavascript("window.shioriExportBackup()") { result ->
            val snapshot = try {
                val json = JSONArray("[$result]").getString(0)
                if (json.toByteArray(Charsets.UTF_8).size > MAX_BACKUP_BYTES ||
                    JSONObject(json).optString("format") != BACKUP_FORMAT
                ) throw IllegalArgumentException("Unsupported backup")
                json
            } catch (_: Exception) {
                notifyUser("Could not read a valid offline task snapshot")
                return@evaluateJavascript
            }
            vaultExecutor.execute {
                val report = runCatching {
                    NativeVault.stageLegacyBackup(shadowPath(), snapshot)
                }.getOrNull()
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) {
                        notifyUser(
                            report ?: "Migration preview failed or conflicts with a prior stage"
                        )
                    }
                }
            }
        }
    }

    /**
     * Read-only comparison of the separate canonical preview against its
     * original archived snapshot and the phone's current tasks. Never
     * promotes the preview or edits either store.
     */
    private fun auditCanonicalShadow() {
        if (isFinishing || isDestroyed) return
        webView.evaluateJavascript("window.shioriExportBackup()") { result ->
            val snapshot = try {
                val json = JSONArray("[$result]").getString(0)
                if (json.toByteArray(Charsets.UTF_8).size > MAX_BACKUP_BYTES ||
                    JSONObject(json).optString("format") != BACKUP_FORMAT
                ) throw IllegalArgumentException("Invalid backup")
                json
            } catch (_: Exception) {
                notifyUser("Could not read a valid offline task snapshot")
                return@evaluateJavascript
            }
            vaultExecutor.execute {
                val report = runCatching {
                    NativeVault.auditLegacyShadow(shadowPath(), snapshot)
                }.getOrNull() ?: "Rust preview audit is unavailable; no tasks were changed."
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) {
                        AlertDialog.Builder(this)
                            .setTitle("Rust migration audit")
                            .setMessage(report)
                            .setPositiveButton("OK", null)
                            .show()
                    }
                }
            }
        }
    }

    /**
     * Experimental native task workspace. It starts with an explicit,
     * user-confirmed, one-time copy of current Android records into a THIRD
     * private SQLite file. Native edits never propagate into WebView tasks.
     */

    /**
     * M2.2 is a diagnostic gate only. User-visible native source switching
     * is deliberately unavailable until the subsequent guarded-cutover PR.
     */
    private fun auditNativeMigrationParity() {
        if (isFinishing || isDestroyed) return
        webView.evaluateJavascript("window.shioriExportBackup()") { rawResult ->
            val snapshot = try {
                val raw = JSONArray("[$rawResult]").getString(0)
                if (raw.toByteArray(Charsets.UTF_8).size > MAX_BACKUP_BYTES ||
                    JSONObject(raw).optString("format") != BACKUP_FORMAT
                ) throw IOException("Unsupported legacy snapshot")
                raw
            } catch (_: Exception) {
                notifyUser("Cannot read current Android tasks for migration comparison")
                return@evaluateJavascript
            }
            vaultExecutor.execute {
                val rawReport = runCatching {
                    NativeVault.stageCutoverCandidate(candidatePath(), snapshot)
                }.getOrNull()
                val result = runCatching { JSONObject(rawReport ?: "") }.getOrNull()
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    val ready = result?.optBoolean("ready", false) == true
                    val count = result?.optInt("task_records", 0) ?: 0
                    val tags = result?.optInt("tag_records", 0) ?: 0
                    val views = result?.optInt("saved_views", 0) ?: 0
                    val fields = result?.optJSONArray("unsupported_fields")
                    AlertDialog.Builder(this)
                        .setTitle(
                            if (ready) "Migration field audit passed"
                            else "Migration cutover blocked"
                        )
                        .setMessage(
                            if (ready) {
                                "$count tasks, $tags tags and $views saved views " +
                                    "verified against separate Rust SQLite records. " +
                                    "Existing Android tasks remain active. " +
                                    "This audit does not switch storage."
                            } else {
                                (result?.optString("reason")?.ifEmpty {
                                    result.optString("error")
                                } ?: "Candidate could not be verified") +
                                    ". Unsupported field types: ${fields?.length() ?: 0}. " +
                                    "No active tasks were changed."
                            }
                        )
                        .setPositiveButton("Close", null)
                        .show()
                }
            }
        }
    }

    private fun openOrCreateWorkingCopy() {
        if (isFinishing || isDestroyed) return
        if (isNativeCanarySelected()) {
            notifyUser("Normal tasks already use Rust SQLite. Roll back before testing another copy.")
            return
        }
        if (File(workingPath()).exists()) {
            notifyWebWorkingReady()
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Create a separate Rust working copy?")
            .setMessage(
                "This creates an experimental, editable SQLite copy of your " +
                    "current Android tasks. The normal task list, saved backups " +
                    "and migration shadow are unchanged. Edits here will NOT " +
                    "appear in your normal task list."
            )
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Create separate copy") { _, _ -> createWorkingCopy() }
            .show()
    }

    private fun notifyWebWorkingReady() {
        if (isFinishing || isDestroyed) return
        webView.evaluateJavascript(
            "window.shioriNativeWorkingReady && window.shioriNativeWorkingReady()", null
        )
    }

    private fun createWorkingCopy() {
        if (isFinishing || isDestroyed) return
        webView.evaluateJavascript("window.shioriExportBackup()") { rawResult ->
            val snapshot = try {
                val json = JSONArray("[$rawResult]").getString(0)
                if (json.toByteArray(Charsets.UTF_8).size > MAX_BACKUP_BYTES ||
                    JSONObject(json).optString("format") != BACKUP_FORMAT
                ) throw IllegalArgumentException("Unsupported backup")
                json
            } catch (_: Exception) {
                notifyUser("Could not read the current Android task records")
                return@evaluateJavascript
            }
            vaultExecutor.execute {
                val message = runCatching {
                    NativeVault.initializeWorkingCopy(workingPath(), snapshot)
                }.getOrNull()
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    if (message == null) {
                        notifyUser(
                            "Could not create the Rust working copy; original tasks unchanged"
                        )
                    } else {
                        notifyUser(message)
                        notifyWebWorkingReady()
                    }
                }
            }
        }
    }

    /**
     * Debug APK only: one-time, opt-in pilot of the normal task UI over Rust.
     * The existing WebView localStorage remains untouched and a separate
     * rollback vault must be readable before the selected flag is written.
     */
    private fun beginGuardedNativeCanary() {
        if (!isDebugCanaryAllowed()) {
            notifyUser("Native cutover is disabled outside SHIORI debug builds")
            return
        }
        if (isNativeCanarySelected()) {
            notifyUser("Native SQLite is already selected")
            return
        }
        if (File(primaryPath()).exists() || File(cutoverRollbackPath()).exists()) {
            notifyUser("An earlier canary database/rollback exists; no files replaced")
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Use Rust SQLite for tasks? Experimental")
            .setMessage(
                "Debug-only storage pilot. We will verify the current task fields, " +
                    "create a permanent independent rollback backup, and switch the " +
                    "normal task UI to a separate native database. Existing Android " +
                    "tasks remain stored in WebView. Rust edits will NOT be merged " +
                    "back if you choose rollback. Real-device validation is pending. " +
                    "Export backups before proceeding."
            )
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Verify and enable") { _, _ ->
                activateGuardedNativeCanary()
            }
            .show()
    }

    private fun activateGuardedNativeCanary() {
        if (isFinishing || isDestroyed) return
        if (!startNativeTransition()) return
        // The JS callback freezes all legacy edits *before* capturing data;
        // a field parity check against an unfrozen snapshot is insufficient.
        webView.evaluateJavascript("window.shioriFreezeLegacyForCutover()") { encoded ->
            val source = try {
                val raw = JSONArray("[$encoded]").getString(0)
                if (raw.toByteArray(Charsets.UTF_8).size > MAX_BACKUP_BYTES ||
                    JSONObject(raw).optString("format") != BACKUP_FORMAT
                ) throw IOException("Invalid Android backup")
                raw
            } catch (_: Exception) {
                finishNativeTransition("window.shioriAbortCutover()")
                notifyUser("Cannot make an unchanged legacy rollback snapshot")
                return@evaluateJavascript
            }
            vaultExecutor.execute {
                var candidateExport: File? = null
                val status = runCatching {
                    if (isNativeCanarySelected() ||
                        File(primaryPath()).exists() ||
                        File(cutoverRollbackPath()).exists()
                    ) throw IOException("A canary already exists")
                    val rawReport = NativeVault.stageCutoverCandidate(candidatePath(), source)
                        ?: throw IOException("Could not validate source parity")
                    val report = JSONObject(rawReport)
                    if (!report.optBoolean("ready", false)) {
                        throw IOException("Migration field audit failed or source changed")
                    }
                    if (!NativeVault.storeSnapshot(cutoverRollbackPath(), source) ||
                        NativeVault.loadSnapshot(cutoverRollbackPath()) != source
                    ) throw IOException("Could not verify independent legacy rollback")
                    candidateExport = File.createTempFile(
                        "shiori-native-primary-", ".sqlite3", filesDir
                    )
                    if (!candidateExport!!.delete()) {
                        throw IOException("Cannot prepare isolated native source")
                    }
                    NativeVault.exportWorkingCopy(
                        candidatePath(), candidateExport!!.absolutePath
                    ) ?: throw IOException("Failed canonical SQLite export verification")
                    val primary = File(primaryPath())
                    installNewPrivateSqlite(candidateExport!!, primary)
                    NativeVault.inspectRecoveredCopy(primary.absolutePath)
                        ?: throw IOException("Native source failed post-install inspection")
                    if (!selectNativeCanary(true)) {
                        throw IOException("Cannot persist canary source selection")
                    }
                    true
                }
                candidateExport?.delete()
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    if (status.isSuccess) {
                        finishNativeTransition("window.shioriNativeActivate()")
                        notifyUser("Rust SQLite debug canary selected; legacy tasks kept")
                    } else {
                        finishNativeTransition("window.shioriAbortCutover()")
                        notifyUser("Native cutover BLOCKED: " +
                            (status.exceptionOrNull()?.message ?: "verification failed"))
                    }
                }
            }
        }
    }

    /**
     * M2.4b: user-initiated resume of an interrupted debug cutover. The old
     * WebView source stays active unless three independent, non-overwritten
     * SQLite artifacts all verify against the current frozen legacy export.
     *
     * This also handles a cutover interrupted before the rollback or primary
     * file was created. If a pre-existing vault/primary is invalid, refuse:
     * never delete or overwrite it just to make progress.
     */
    private fun beginResumeInterruptedCanary() {
        if (!isDebugCanaryAllowed()) {
            notifyUser("Interrupted native cutover recovery is debug-only")
            return
        }
        if (isNativeCanarySelected()) {
            notifyUser("Rust SQLite is already selected; use its regular task view")
            return
        }
        if (!File(candidatePath()).isFile) {
            notifyUser("No staged migration candidate exists. Run field parity first.")
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Resume interrupted native cutover?")
            .setMessage(
                "Experimental debug-only recovery. SHIORI will verify your " +
                    "original Android tasks and every existing native cutover " +
                    "file. Missing independent backup stages may be completed, " +
                    "but existing files will NEVER be overwritten. If a previous " +
                    "native database has changed, the operation is refused. " +
                    "Keep external backups before proceeding."
            )
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Verify and resume") { _, _ ->
                resumeInterruptedCanary()
            }
            .show()
    }

    private fun resumeInterruptedCanary() {
        if (isFinishing || isDestroyed) return
        if (!startNativeTransition()) return
        webView.evaluateJavascript("window.shioriFreezeLegacyForCutover()") { encoded ->
            val source = try {
                val raw = JSONArray("[$encoded]").getString(0)
                if (raw.toByteArray(Charsets.UTF_8).size > MAX_BACKUP_BYTES ||
                    JSONObject(raw).optString("format") != BACKUP_FORMAT
                ) throw IOException("Invalid Android backup")
                raw
            } catch (_: Exception) {
                finishNativeTransition("window.shioriAbortCutover()")
                notifyUser("Cannot capture unchanged Android source for native recovery")
                return@evaluateJavascript
            }

            vaultExecutor.execute {
                var candidateExport: File? = null
                val status = runCatching {
                    if (isNativeCanarySelected() || !File(candidatePath()).isFile) {
                        throw IOException("Cutover source is missing or already active")
                    }
                    // The validator reads existing files only; no migration
                    // DB creation, data deletion, or hidden file replacement.
                    fun inspect(): JSONObject {
                        val raw = NativeVault.inspectInterruptedCanary(
                            candidatePath(), cutoverRollbackPath(), primaryPath(), source
                        ) ?: throw IOException("Native cutover inspection unavailable")
                        val report = JSONObject(raw)
                        if (!report.optBoolean("ok", false)) {
                            throw IOException(
                                report.optString("error", "Interrupted cutover is not safe to resume")
                            )
                        }
                        return report
                    }

                    val initial = inspect()
                    if (initial.optBoolean("needs_rollback_vault", false)) {
                        if (File(cutoverRollbackPath()).exists()) {
                            throw IOException("Existing rollback vault must not be replaced")
                        }
                        if (!NativeVault.storeSnapshot(cutoverRollbackPath(), source) ||
                            NativeVault.loadSnapshot(cutoverRollbackPath()) != source
                        ) throw IOException("New rollback vault could not be verified")
                    }
                    // Check again before copying: if a new rollback vault
                    // differs from the source, stop without touching primary.
                    val afterVault = inspect()
                    if (afterVault.optBoolean("needs_native_primary", false)) {
                        if (File(primaryPath()).exists()) {
                            throw IOException("Existing native primary must not be replaced")
                        }
                        candidateExport = File.createTempFile(
                            "shiori-native-resume-", ".sqlite3", filesDir
                        )
                        if (!candidateExport!!.delete()) {
                            throw IOException("Cannot prepare native recovery staging")
                        }
                        NativeVault.exportWorkingCopy(
                            candidatePath(), candidateExport!!.absolutePath
                        ) ?: throw IOException("Cannot verify new native SQLite source")
                        installNewPrivateSqlite(
                            candidateExport!!, File(primaryPath())
                        )
                    }
                    val final = inspect()
                    if (!final.optBoolean("ready", false)) {
                        throw IOException("Verified cutover stages are incomplete")
                    }
                    if (!selectNativeCanary(true)) {
                        throw IOException("Could not persist verified Rust source selection")
                    }
                    true
                }
                // Delete only our temporary export, never primary, migration
                // candidate, recovery archive or rollback vault.
                candidateExport?.delete()
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    if (status.isSuccess) {
                        finishNativeTransition("window.shioriNativeActivate()")
                        notifyUser("Verified native cutover resumed; legacy tasks preserved")
                    } else {
                        finishNativeTransition("window.shioriAbortCutover()")
                        notifyUser(
                            "Cannot resume native source: " +
                                (status.exceptionOrNull()?.message ?: "validation failed")
                        )
                    }
                }
            }
        }
    }

    private fun rollbackNativeCanary() {
        if (!isNativeCanarySelected()) {
            notifyUser("Android WebView tasks are already selected")
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Return to the original Android tasks?")
            .setMessage(
                "The original WebView tasks are unchanged. Switching back will " +
                    "NOT copy native-only edits into them. The native database and " +
                    "its independent backup remain on this device. Export a " +
                    "native SQLite backup before rolling back."
            )
            .setNegativeButton("Keep Rust source", null)
            .setPositiveButton("Verify and return") { _, _ ->
                verifyAndRollbackNativeCanary()
            }
            .show()
    }

    /**
     * A debug canary may only switch back to WebView after checking that
     * current legacy localStorage is unchanged from BOTH the independent
     * rollback vault and the canonical migration candidate. Freeze UI
     * mutations until the native audit and selected-source commit finish.
     * This prevents silently reopening stale or modified legacy records.
     */
    private fun verifyAndRollbackNativeCanary() {
        if (isFinishing || isDestroyed) return
        if (!startNativeTransition()) return
        webView.evaluateJavascript("window.shioriNativeFreezeForRollback()") { encoded ->
            val legacy = try {
                val raw = JSONArray("[$encoded]").getString(0)
                if (raw.toByteArray(Charsets.UTF_8).size > MAX_BACKUP_BYTES ||
                    JSONObject(raw).optString("format") != BACKUP_FORMAT
                ) throw IOException("Legacy source cannot be inspected")
                raw
            } catch (_: Exception) {
                finishNativeTransition("window.shioriAbortCutover()")
                notifyUser("Cannot verify rollback while a native task operation is running")
                return@evaluateJavascript
            }
            vaultExecutor.execute {
                val checked = runCatching {
                    NativeVault.verifyLegacyRollback(
                        cutoverRollbackPath(), candidatePath(), legacy
                    )
                }.getOrDefault(false)
                runOnUiThread {
                    if (isFinishing || isDestroyed) return@runOnUiThread
                    if (!checked) {
                        finishNativeTransition("window.shioriAbortCutover()")
                        notifyUser(
                            "Rollback BLOCKED: preserved legacy tasks no longer match " +
                                "the migration backup. Native source remains selected."
                        )
                    } else if (!selectNativeCanary(false)) {
                        finishNativeTransition("window.shioriAbortCutover()")
                        notifyUser("Cannot save rollback selection; Rust remains active")
                    } else {
                        finishNativeTransition("window.shioriNativeDeactivate()")
                        notifyUser("Verified rollback: original Android tasks selected")
                    }
                }
            }
        }
    }

    /**
     * One-at-a-time, typed request/response bridge for the appassets origin.
     * Web content signals a fixed custom URL; Kotlin pulls the request from
     * the bundled JS and runs allowlisted operations on its serial I/O worker.
     * No arbitrary SQLite paths, JNI objects, file access or web requests
     * are exposed to JavaScript.
     */
    private fun receiveNativeWorkingCommand() {
        if (isFinishing || isDestroyed ||
            webView.url != "https://$HOST/index.html"
        ) return
        webView.evaluateJavascript("window.shioriNativeTakeRequest()") { encoded ->
            val request = try {
                val raw = JSONArray("[$encoded]").getString(0)
                if (raw.toByteArray(Charsets.UTF_8).size > MAX_NATIVE_COMMAND_BYTES) {
                    throw IllegalArgumentException("Native command exceeds size limit")
                }
                JSONObject(raw)
            } catch (_: Exception) {
                return@evaluateJavascript
            }
            val requestId = request.optString("request_id")
            if (!requestId.matches(Regex("[1-9][0-9]{0,11}"))) return@evaluateJavascript

            val action = request.optString("op")
            val supported = action in setOf(
                "list", "create", "rename", "edit", "status", "delete", "metadata"
            )
            val expectsPrimary = isNativeCanarySelected()
            val source = request.optString("source", "working")
            val requiredSource = if (expectsPrimary) "primary" else "working"
            if (request.optString("protocol") != "shiori-native-working-v1" ||
                !supported || source != requiredSource
            ) {
                completeNativeWorkingCommand(
                    requestId, JSONObject().put("ok", false)
                        .put("error", "Unsupported command or stale task source").toString()
                )
                return@evaluateJavascript
            }
            vaultExecutor.execute {
                val answer = runCatching {
                    if (expectsPrimary != isNativeCanarySelected()) {
                        throw IOException("Task source changed before this operation")
                    }
                    NativeVault.workingCopyRequest(
                        if (expectsPrimary) primaryPath() else workingPath(),
                        request.toString()
                    )
                }.getOrNull()
                val result = if (answer == null ||
                    answer.toByteArray(Charsets.UTF_8).size > MAX_NATIVE_RESPONSE_BYTES
                ) {
                    JSONObject().put("ok", false)
                        .put("error", "Native operation failed or response too large")
                        .toString()
                } else {
                    answer
                }
                runOnUiThread {
                    completeNativeWorkingCommand(requestId, result)
                }
            }
        }
    }

    private fun completeNativeWorkingCommand(requestId: String, json: String) {
        if (isFinishing || isDestroyed ||
            webView.url != "https://$HOST/index.html"
        ) return
        webView.evaluateJavascript(
            "window.shioriNativeComplete(" +
                JSONObject.quote(requestId) + "," + JSONObject.quote(json) + ")", null
        )
    }

    /**
     * Separate, explicitly requested SQLite backup of the experimental native
     * working copy. SQLite VACUUM INTO produces a consistent private staging
     * file even when the source uses WAL. Only Android's document picker can
     * choose a destination. There is no native restore/cutover action here.
     */
    private fun beginNativeDatabaseExport() {
        if (!File(if (isNativeCanarySelected()) primaryPath() else workingPath()).isFile) {
            notifyUser("Create a Rust working copy before exporting its database")
            return
        }
        if (pendingNativeExport != null) {
            notifyUser("Complete or cancel the current native database export")
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Export native Rust task database?")
            .setMessage(
                "Create an independent SQLite backup of the experimental Rust " +
                    "working copy, including its edited tasks, deleted-record " +
                    "history, dependencies and original import archive. " +
                    "Your normal Android tasks will not change. " +
                    "An isolated verified recovery preview is supported, " +
                    "but restoring directly into live tasks is not yet supported."
            )
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Choose backup location") { _, _ ->
                prepareNativeDatabaseExport()
            }
            .show()
    }

    private fun prepareNativeDatabaseExport() {
        vaultExecutor.execute {
            var staging: File? = null
            val ready = runCatching {
                staging = File.createTempFile("shiori-native-export-", ".sqlite3", cacheDir)
                // SQLite VACUUM INTO requires a new destination; delete the
                // zero-byte placeholder before Rust creates its snapshot.
                if (!staging!!.delete()) throw IOException("Cannot prepare staging path")
                val report = NativeVault.exportWorkingCopy(
                    if (isNativeCanarySelected()) primaryPath() else workingPath(),
                    staging!!.absolutePath
                ) ?: throw IOException("Native SQLite export failed verification")
                if (!staging!!.isFile ||
                    staging!!.length() == 0L ||
                    staging!!.length() > MAX_NATIVE_EXPORT_BYTES
                ) throw IOException("Invalid SQLite export size")
                report
            }
            if (ready.isFailure) {
                staging?.delete()
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) notifyUser(
                        "Native SQLite backup failed; original tasks were kept"
                    )
                }
                return@execute
            }
            runOnUiThread {
                if (isFinishing || isDestroyed) {
                    staging?.delete()
                    return@runOnUiThread
                }
                pendingNativeExport = staging
                val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "application/vnd.sqlite3"
                    putExtra(Intent.EXTRA_TITLE, "SHIORI-native-working-backup.sqlite3")
                }
                try {
                    startActivityForResult(intent, NATIVE_EXPORT_REQUEST)
                } catch (_: Exception) {
                    pendingNativeExport?.delete()
                    pendingNativeExport = null
                    notifyUser("Could not open the document picker")
                }
            }
        }
    }

    /**
     * User-initiated recovery trial only. An Android DocumentsProvider is
     * allowed to supply bytes, never app-private database paths. The Rust
     * validator runs on a private copy using the serial I/O executor.
     */
    private fun beginIsolatedDatabaseRecovery() {
        if (nativeRecoveryPending) {
            notifyUser("Complete the existing native backup recovery first")
            return
        }
        if (File(recoveredPath()).exists()) {
            notifyUser("An isolated recovery already exists. Inspect it; no files were replaced.")
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Stage a separate SQLite recovery?")
            .setMessage(
                "Choose a SHIORI native SQLite backup. It will be verified and " +
                    "restored into an independent, inactive database. It will NOT " +
                    "replace your Android tasks, native working copy, or any existing " +
                    "backup. This preview cannot be promoted automatically."
            )
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Select SQLite backup") { _, _ ->
                nativeRecoveryPending = true
                val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    // Document providers differ in SQLite MIME types.
                    type = "*/*"
                }
                try {
                    startActivityForResult(intent, NATIVE_RECOVERY_REQUEST)
                } catch (_: Exception) {
                    nativeRecoveryPending = false
                    notifyUser("Could not open the backup document picker")
                }
            }
            .show()
    }

    private fun inspectIsolatedRecovery() {
        val recovered = File(recoveredPath())
        if (!recovered.isFile) {
            notifyUser("No isolated recovered SQLite database is available")
            return
        }
        vaultExecutor.execute {
            val message = runCatching {
                NativeVault.inspectRecoveredCopy(recovered.absolutePath)
            }.getOrNull()
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                AlertDialog.Builder(this)
                    .setTitle("Isolated SQLite recovery")
                    .setMessage(
                        message ?: "Recovered preview could not be verified. " +
                            "No active task store was changed."
                    )
                    .setPositiveButton("Close", null)
                    .show()
            }
        }
    }

    /**
     * Bound the bytes supplied by an untrusted document provider before
     * passing its app-private staging path to the native SQLite validator.
     */
    private fun stageSelectedSqliteBackup(uri: Uri): File {
        val staged = File.createTempFile("shiori-recovery-input-", ".sqlite3", cacheDir)
        try {
            val source = contentResolver.openInputStream(uri)
                ?: throw IOException("Could not open selected document")
            source.use { input ->
                staged.outputStream().use { output ->
                    val buf = ByteArray(8192)
                    var total = 0L
                    while (true) {
                        val size = input.read(buf)
                        if (size < 0) break
                        if (size == 0) continue
                        total += size.toLong()
                        if (total > MAX_NATIVE_EXPORT_BYTES) {
                            throw IOException("Native SQLite backup exceeds 64 MB")
                        }
                        output.write(buf, 0, size)
                    }
                    if (total == 0L) throw IOException("Selected backup is empty")
                }
            }
            return staged
        } catch (error: Exception) {
            staged.delete()
            throw error
        }
    }

    private fun processIsolatedRecovery(uri: Uri) {
        vaultExecutor.execute {
            var input: File? = null
            var candidate: File? = null
            val status = runCatching {
                // Refuse overwriting an existing recovery, even on a second
                // picker result or a recovered Activity.
                val target = File(recoveredPath())
                if (target.exists()) throw IOException("Recovery preview already exists")
                input = stageSelectedSqliteBackup(uri)
                candidate = File.createTempFile(
                    "shiori-recovery-verified-", ".sqlite3", filesDir
                )
                if (!candidate!!.delete()) throw IOException("Cannot prepare recovery path")
                val report = NativeVault.recoverWorkingCopy(
                    input!!.absolutePath, candidate!!.absolutePath
                ) ?: throw IOException("SQLite backup failed native validation")
                installNewPrivateSqlite(candidate!!, target)
                val inspected = NativeVault.inspectRecoveredCopy(target.absolutePath)
                if (inspected == null) {
                    // We just created this path; remove only this unverified
                    // recovery, never another pre-existing user database.
                    target.delete()
                    throw IOException("Committed recovered preview did not verify")
                }
                "$report. $inspected"
            }
            input?.delete()
            candidate?.delete()
            runOnUiThread {
                nativeRecoveryPending = false
                if (isFinishing || isDestroyed) return@runOnUiThread
                AlertDialog.Builder(this)
                    .setTitle(if (status.isSuccess) "Recovery preview created" else "Recovery refused")
                    .setMessage(
                        status.getOrElse {
                            "The selected SQLite backup was invalid, incompatible, " +
                                "already recovered, or could not be staged. " +
                                "Your existing Android tasks and working database were not changed."
                        }
                    )
                    .setPositiveButton("Close", null)
                    .show()
            }
        }
    }

    private fun recoverVaultCopy() {
        vaultExecutor.execute {
            val snapshot = runCatching { NativeVault.loadSnapshot(vaultPath()) }.getOrNull()
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                if (snapshot == null) {
                    notifyUser("No native SQLite safety copy is available")
                } else {
                    try {
                        askToRestore(snapshot)
                    } catch (_: Exception) {
                        notifyUser("Native safety copy could not be read")
                    }
                }
            }
        }
    }

    /**
     * Backup uses Storage Access Framework document pickers, not broad storage
     * permissions or a JavaScript-to-native interface. Native code only
     * evaluates dedicated JS functions on our private bundled origin.
     */
    @Suppress("DEPRECATION")
    private fun beginExport() {
        webView.evaluateJavascript("window.shioriExportBackup()") { value ->
            try {
                val json = JSONArray("[$value]").getString(0)
                if (json.toByteArray(Charsets.UTF_8).size > MAX_BACKUP_BYTES ||
                    JSONObject(json).optString("format") != BACKUP_FORMAT
                ) throw IllegalArgumentException("Invalid export")
                pendingExportJson = json
                val intent = Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "application/json"
                    putExtra(Intent.EXTRA_TITLE, "SHIORI-offline-backup.json")
                }
                startActivityForResult(intent, EXPORT_REQUEST)
            } catch (_: Exception) {
                notifyUser("Cannot export this backup. Check available device storage.")
            }
        }
    }

    @Suppress("DEPRECATION")
    private fun beginImport() {
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "application/json"
        }
        startActivityForResult(intent, IMPORT_REQUEST)
    }

    private fun readBackup(uri: Uri): String {
        val stream = contentResolver.openInputStream(uri)
            ?: throw IOException("Document cannot be opened")
        stream.use { input ->
            val buffer = ByteArray(8192)
            val bytes = ByteArrayOutputStream()
            while (true) {
                val read = input.read(buffer)
                if (read == -1) break
                if (bytes.size() + read > MAX_BACKUP_BYTES) {
                    throw IOException("Backup exceeds size limit")
                }
                bytes.write(buffer, 0, read)
            }
            return bytes.toString(Charsets.UTF_8.name())
        }
    }

    private fun askToRestore(json: String) {
        val parsed = JSONObject(json)
        if (parsed.optString("format") != BACKUP_FORMAT) {
            throw IOException("Not a SHIORI Android backup")
        }
        val records = parsed.optJSONArray("tasks") ?: throw IOException("No task records")
        if (records.length() > 5000) throw IOException("Too many task records")
        AlertDialog.Builder(this)
            .setTitle("Restore SHIORI backup?")
            .setMessage(
                "Replace this device's current offline task records with " +
                    "${records.length()} tasks from the selected backup? " +
                    "This cannot be undone without another saved backup."
            )
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Restore") { _, _ ->
                webView.evaluateJavascript(
                    "window.shioriRestoreBackup(${JSONObject.quote(json)})"
                ) { result ->
                    notifyUser(
                        if (result == "true") "SHIORI backup restored"
                        else "Backup was rejected; existing tasks were kept"
                    )
                }
            }
            .show()
    }

    @Deprecated("Legacy Activity result callback used without AndroidX dependencies")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == EXPORT_REQUEST) {
            val json = pendingExportJson
            pendingExportJson = null
            if (resultCode != RESULT_OK || data?.data == null || json == null) return
            try {
                val stream = contentResolver.openOutputStream(data.data!!, "w")
                    ?: throw IOException("Cannot write backup")
                stream.use { it.write(json.toByteArray(Charsets.UTF_8)) }
                notifyUser("Backup saved to selected document")
            } catch (_: Exception) {
                notifyUser("Backup could not be written")
            }
        } else if (requestCode == NATIVE_EXPORT_REQUEST) {
            val staged = pendingNativeExport
            pendingNativeExport = null
            if (staged == null) {
                if (resultCode == RESULT_OK) {
                    notifyUser("Native backup staging was lost; export again. No source changed.")
                }
                return
            }
            val destination = if (resultCode == RESULT_OK) data?.data else null
            if (destination == null) {
                staged.delete()
                return
            }
            vaultExecutor.execute {
                val saved = runCatching {
                    val output = contentResolver.openOutputStream(destination, "wt")
                        ?: throw IOException("Document cannot be written")
                    output.use { stream ->
                        staged.inputStream().use { input ->
                            val count = input.copyTo(stream, 8192)
                            if (count <= 0 || count != staged.length()) {
                                throw IOException("Incomplete native SQLite backup")
                            }
                        }
                    }
                }.isSuccess
                staged.delete()
                runOnUiThread {
                    if (!isFinishing && !isDestroyed) notifyUser(
                        if (saved) "Rust SQLite backup saved to your selected document"
                        else "Native SQLite backup could not be written; original tasks unchanged"
                    )
                }
            }
        } else if (requestCode == NATIVE_RECOVERY_REQUEST) {
            val uri = if (resultCode == RESULT_OK) data?.data else null
            if (uri == null) {
                nativeRecoveryPending = false
                return
            }
            processIsolatedRecovery(uri)
        } else if (requestCode == IMPORT_REQUEST) {
            if (resultCode != RESULT_OK || data?.data == null) return
            try {
                askToRestore(readBackup(data.data!!))
            } catch (_: Exception) {
                notifyUser("Invalid or unreadable backup; no tasks changed")
            }
        }
    }

    private fun notifyUser(message: String) {
        Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    /**
     * Hardware/gesture Back first dismisses an open SHIORI dialog. The web UI
     * tells Android whether the event was consumed before navigating away.
     */
    private fun navigateBack() {
        if (!::webView.isInitialized) {
            finish()
            return
        }
        webView.evaluateJavascript(
            "(function(){const event=new Event('shiori-native-back'," +
                "{cancelable:true});window.dispatchEvent(event);" +
                "return event.defaultPrevented;})()"
        ) { consumed ->
            if (isFinishing || isDestroyed) return@evaluateJavascript
            if (consumed != "true") {
                if (webView.canGoBack()) webView.goBack() else finish()
            }
        }
    }

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        navigateBack()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        pendingNativeExport?.takeIf { it.isFile }?.let {
            outState.putString(STATE_PENDING_NATIVE_EXPORT, it.absolutePath)
        }
        outState.putBoolean(STATE_RECOVERY_PICKER_PENDING, nativeRecoveryPending)
        super.onSaveInstanceState(outState)
    }

    override fun onDestroy() {
        // Keep a staged export only when Android is recreating this Activity
        // (e.g., rotation with the document picker open). Cancellation or
        // normal Activity destruction still removes transient private data.
        if (!isChangingConfigurations) pendingNativeExport?.delete()
        pendingNativeExport = null
        vaultExecutor.shutdown()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            backCallback?.let {
                onBackInvokedDispatcher.unregisterOnBackInvokedCallback(it)
            }
            backCallback = null
        }
        webView.destroy()
        super.onDestroy()
    }

    companion object {
        private const val HOST = "appassets.androidplatform.net"
        private const val BACKUP_FORMAT = "shiori-android-local-v1"
        private const val MAX_BACKUP_BYTES = 2_000_000
        private const val MAX_NATIVE_COMMAND_BYTES = 16_384
        private const val MAX_NATIVE_RESPONSE_BYTES = 768_000
        private const val MAX_NATIVE_EXPORT_BYTES = 64L * 1024L * 1024L
        private const val EXPORT_REQUEST = 4001
        private const val IMPORT_REQUEST = 4002
        private const val NATIVE_EXPORT_REQUEST = 4003
        private const val NATIVE_RECOVERY_REQUEST = 4004
        private const val STATE_PENDING_NATIVE_EXPORT =
            "shiori.lifecycle.pending_native_export"
        private const val STATE_RECOVERY_PICKER_PENDING =
            "shiori.lifecycle.recovery_picker_pending"
    }
}
