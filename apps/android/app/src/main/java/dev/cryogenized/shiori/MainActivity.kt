package dev.cryogenized.shiori

import android.app.Activity
import android.os.Bundle
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

    @Suppress("DEPRECATION")
    override fun onBackPressed() {
        if (webView.canGoBack()) webView.goBack() else super.onBackPressed()
    }

    override fun onDestroy() {
        webView.destroy()
        super.onDestroy()
    }

    companion object {
        private const val HOST = "appassets.androidplatform.net"
    }
}
