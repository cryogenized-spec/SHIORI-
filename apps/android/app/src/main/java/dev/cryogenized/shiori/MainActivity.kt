package dev.cryogenized.shiori

import android.app.Activity
import android.app.AlertDialog
import android.util.Log
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import android.widget.EditText
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
import java.io.ByteArrayInputStream
import java.io.InputStream

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
    private val vaultExecutor = Executors.newSingleThreadExecutor()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        webView = WebView(this)
        webView.setBackgroundColor(android.graphics.Color.rgb(23, 21, 30))
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = false
            allowContentAccess = false
            javaScriptCanOpenWindowsAutomatically = false
            setSupportMultipleWindows(false)
            cacheMode = WebSettings.LOAD_DEFAULT
        }

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
    private fun openOrCreateWorkingCopy() {
        if (File(workingPath()).exists()) {
            showWorkingCopy()
            return
        }
        AlertDialog.Builder(this)
            .setTitle("Create an editable Rust working copy?")
            .setMessage(
                "Make a separate experimental copy of your current tasks to test " +
                    "native Rust task editing. Your existing Android task list, " +
                    "JSON backups and migration preview will remain unchanged. " +
                    "Changes in this working copy will NOT appear in your normal list."
            )
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Create separate copy") { _, _ -> createWorkingCopy() }
            .show()
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
                        notifyUser("Could not create a safe Rust working copy; original tasks unchanged")
                    } else {
                        notifyUser(message)
                        showWorkingCopy()
                    }
                }
            }
        }
    }

    private fun workingCommand(action: JSONObject): JSONObject {
        action.put("protocol", "shiori-native-working-v1")
        val raw = NativeVault.workingCopyRequest(workingPath(), action.toString())
            ?: throw IOException("Native task engine is unavailable")
        return JSONObject(raw)
    }

    /** All native task I/O is serialized away from Android's UI thread. */
    private fun showWorkingCopy() {
        vaultExecutor.execute {
            val result = runCatching {
                workingCommand(JSONObject().put("op", "list"))
            }.getOrElse { JSONObject().put("ok", false).put("error", "Could not read native tasks") }
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                if (!result.optBoolean("ok")) {
                    AlertDialog.Builder(this)
                        .setTitle("Native working copy unavailable")
                        .setMessage(
                            result.optString("error", "Unknown error") +
                                ". Original Android tasks were not changed."
                        )
                        .setPositiveButton("OK", null)
                        .show()
                    return@runOnUiThread
                }
                val rows = result.optJSONArray("tasks") ?: JSONArray()
                val labels = Array(rows.length()) { index ->
                    val task = rows.getJSONObject(index)
                    val status = task.optString("status")
                    val mark = if (status == "done") "✓ " else "○ "
                    mark + task.optString("title") + " · " + task.optString("project")
                }
                val total = result.optInt("total")
                val builder = AlertDialog.Builder(this)
                    .setTitle("Native Rust tasks · working copy")
                    .setMessage(
                        "Experimental, separate SQLite copy. These edits do not affect your " +
                            "normal Android tasks. Showing ${rows.length()} of $total records."
                    )
                    .setNeutralButton("Add task") { _, _ -> promptNativeTask() }
                    .setNegativeButton("Close", null)
                    .setPositiveButton("Refresh") { _, _ -> showWorkingCopy() }
                if (labels.isNotEmpty()) {
                    builder.setItems(labels) { _, index ->
                        showNativeTaskActions(rows.getJSONObject(index))
                    }
                }
                builder.show()
            }
        }
    }

    private fun promptNativeTask() {
        val input = EditText(this).apply {
            hint = "Native task title"
            isSingleLine = true
        }
        AlertDialog.Builder(this)
            .setTitle("Add to Rust working copy")
            .setView(input)
            .setNegativeButton("Cancel", null)
            .setPositiveButton("Add") { _, _ ->
                val title = input.text.toString().trim()
                if (title.isEmpty()) {
                    notifyUser("Task title cannot be empty")
                } else {
                    sendWorkingMutation(JSONObject()
                        .put("op", "create")
                        .put("title", title)
                        .put("project", "Native preview")
                        .put("priority", "medium"))
                }
            }
            .show()
    }

    private fun showNativeTaskActions(task: JSONObject) {
        val complete = task.optString("status") == "done"
        val actions = arrayOf(
            "Rename in working copy",
            if (complete) "Reopen in working copy" else "Complete in working copy",
            "Soft-delete from working copy"
        )
        AlertDialog.Builder(this)
            .setTitle(task.optString("title"))
            .setMessage("These actions affect only the separate Rust working copy.")
            .setItems(actions) { _, selected ->
                val id = task.getString("id")
                val version = task.getLong("version")
                when (selected) {
                    0 -> {
                        val input = EditText(this).apply {
                            setText(task.optString("title"))
                            isSingleLine = true
                        }
                        AlertDialog.Builder(this)
                            .setTitle("Rename native task")
                            .setView(input)
                            .setNegativeButton("Cancel", null)
                            .setPositiveButton("Save") { _, _ ->
                                sendWorkingMutation(JSONObject()
                                    .put("op", "rename")
                                    .put("id", id)
                                    .put("expected_version", version)
                                    .put("title", input.text.toString().trim()))
                            }.show()
                    }
                    1 -> sendWorkingMutation(JSONObject()
                        .put("op", "status")
                        .put("id", id)
                        .put("expected_version", version)
                        .put("status", if (complete) "todo" else "done"))
                    2 -> AlertDialog.Builder(this)
                        .setTitle("Delete from Rust working copy?")
                        .setMessage(
                            "This preserves a deletion record in the separate Rust database. " +
                                "Your normal Android tasks are untouched."
                        )
                        .setNegativeButton("Cancel", null)
                        .setPositiveButton("Delete from copy") { _, _ ->
                            sendWorkingMutation(JSONObject()
                                .put("op", "delete")
                                .put("id", id)
                                .put("expected_version", version))
                        }.show()
                }
            }
            .setNegativeButton("Back") { _, _ -> showWorkingCopy() }
            .show()
    }

    private fun sendWorkingMutation(action: JSONObject) {
        vaultExecutor.execute {
            val result = runCatching { workingCommand(action) }.getOrElse {
                JSONObject().put("ok", false).put("error", "Native storage unavailable")
            }
            runOnUiThread {
                if (isFinishing || isDestroyed) return@runOnUiThread
                if (result.optBoolean("ok")) {
                    notifyUser("Saved to Rust working copy only")
                    showWorkingCopy()
                } else {
                    AlertDialog.Builder(this)
                        .setTitle("Native task not changed")
                        .setMessage(result.optString("error", "Operation rejected"))
                        .setPositiveButton("OK") { _, _ -> showWorkingCopy() }
                        .show()
                }
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

    override fun onDestroy() {
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
        private const val EXPORT_REQUEST = 4001
        private const val IMPORT_REQUEST = 4002
    }
}
