package dev.cryogenized.shiori

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.net.Uri
import android.widget.Toast
import org.json.JSONArray
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.IOException
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
