package dev.cryogenized.shiori

import android.os.SystemClock
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * M2.5b: Android instrumentation. Unlike a browser-origin simulation, this
 * test uses the actual bundled Android WebView and injects pointer touches
 * through Android Instrumentation.sendPointerSync. JavaScript only INSPECTS
 * the resulting DOM/storage state and scrolls elements into the viewport.
 *
 * Each test operates on the dedicated CI emulator/test APK. It does NOT
 * verify a physical handset or give permission to test real user records.
 */
@RunWith(AndroidJUnit4::class)
class WebViewTouchAcceptanceTest {
    private val instrument = InstrumentationRegistry.getInstrumentation()
    private lateinit var scenario: ActivityScenario<MainActivity>
    private lateinit var webView: WebView

    @Before
    fun launchCleanActivity() {
        scenario = ActivityScenario.launch(MainActivity::class.java)
        captureWebView()
        await("bundled offline WebView initialisation") {
            javascript("typeof window.shioriExportBackup === 'function' && " +
                "document.querySelector('#taskModal') !== null") == "true"
        }
    }

    @After
    fun closeActivity() {
        scenario.close()
    }

    private fun findWebView(view: View): WebView? {
        if (view is WebView) return view
        if (view is ViewGroup) {
            for (index in 0 until view.childCount) {
                findWebView(view.getChildAt(index))?.let { return it }
            }
        }
        return null
    }

    private fun captureWebView() {
        scenario.onActivity { activity ->
            webView = findWebView(activity.window.decorView)
                ?: error("SHIORI Android Activity has no WebView")
        }
    }

    private fun javascript(code: String): String {
        val latch = CountDownLatch(1)
        var value = "null"
        instrument.runOnMainSync {
            webView.evaluateJavascript(code) { result ->
                value = result ?: "null"
                latch.countDown()
            }
        }
        assertTrue("WebView JavaScript result timed out", latch.await(8, TimeUnit.SECONDS))
        return value.trim()
    }

    private fun await(label: String, predicate: () -> Boolean) {
        val deadline = SystemClock.uptimeMillis() + 25_000L
        while (SystemClock.uptimeMillis() < deadline) {
            if (predicate()) return
            Thread.sleep(160)
        }
        throw AssertionError("Android WebView acceptance timed out: $label")
    }

    private fun modalOpen(): Boolean =
        javascript("document.querySelector('#taskModal')?.classList.contains('open') === true") == "true"

    private fun taskExists(title: String): Boolean {
        val literal = JSONObject.quote(title)
        return javascript(
            "(function(){try {const rows=JSON.parse(localStorage.getItem(" +
                "'shiori-android-local-tasks')||'[]'); return Array.isArray(rows) && " +
                "rows.some(t=>t.title===$literal);}catch(e){return false;}})()"
        ) == "true"
    }

    /**
     * Read the DOM center in CSS pixels, then transform to Android screen
     * pixels using the actual WebView viewport width and view location.
     * All taps are real Android pointer events, never JS .click() calls.
     */
    private fun touch(selector: String) {
        val quoted = JSONObject.quote(selector)
        javascript(
            "(function(){const e=document.querySelector($quoted); " +
                "if(e) e.scrollIntoView({block:'center',inline:'nearest'});return !!e;})()"
        ).let { assertEquals("Missing element for touch: $selector", "true", it) }
        instrument.waitForIdleSync()
        val bounds = JSONObject(
            javascript(
                "(function(){const e=document.querySelector($quoted);" +
                    "if(!e)return null;const r=e.getBoundingClientRect();" +
                    "return {x:r.left+r.width/2,y:r.top+r.height/2," +
                    "width:r.width,height:r.height,viewport:window.innerWidth};})()"
            )
        )
        assertTrue("Element is not laid out: $selector", bounds.getDouble("width") > 1)
        assertTrue("Element is not laid out: $selector", bounds.getDouble("height") > 1)
        val location = IntArray(2)
        var width = 0
        instrument.runOnMainSync {
            webView.getLocationOnScreen(location)
            width = webView.width
        }
        val scale = width.toDouble() / bounds.getDouble("viewport")
        val x = (location[0] + bounds.getDouble("x") * scale).toFloat()
        val y = (location[1] + bounds.getDouble("y") * scale).toFloat()
        val start = SystemClock.uptimeMillis()
        val down = MotionEvent.obtain(start, start, MotionEvent.ACTION_DOWN, x, y, 0)
        val up = MotionEvent.obtain(start, start + 75, MotionEvent.ACTION_UP, x, y, 0)
        try {
            instrument.sendPointerSync(down)
            instrument.sendPointerSync(up)
            instrument.waitForIdleSync()
        } finally {
            down.recycle()
            up.recycle()
        }
    }

    @Test
    fun touchXCancelAndAndroidBackNeverSaveDismissedTask() {
        val unsavedTitle = "Uncommitted M25b task"
        assertTrue("Must begin with an editable legacy source",
            javascript("!document.querySelector('[data-add]').disabled") == "true")
        touch(".mobile-fab")
        await("new task modal opens from an actual Android tap") { modalOpen() }
        touch("#taskModal .modal-head [data-close-modal]")
        await("header X dismisses new-task modal") { !modalOpen() }

        touch(".mobile-fab")
        await("new task modal opens again") { modalOpen() }
        touch("#taskName")
        instrument.sendStringSync(unsavedTitle)
        await("actual Android keyboard input reaches the form") {
            javascript("document.querySelector('#taskName').value === " +
                JSONObject.quote(unsavedTitle)) == "true"
        }
        touch("#taskForm [data-close-modal]")
        await("Cancel dismisses task with unsaved typing") { !modalOpen() }
        assertTrue("Cancel created a task unexpectedly", !taskExists(unsavedTitle))

        touch(".mobile-fab")
        await("modal opens before Back") { modalOpen() }
        // Depending on the IME state, the first Back may hide the keyboard.
        // Android Back must dismiss the modal by the second invocation.
        instrument.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
        if (modalOpen()) {
            instrument.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
        }
        await("Android Back dismisses modal without finishing Activity") { !modalOpen() }
        assertTrue("Android Back changed unsaved records", !taskExists(unsavedTitle))
    }

    @Test
    fun touchToCreatePersistsAcrossNativeActivityRecreation() {
        val title = "M25b on-device " + SystemClock.uptimeMillis().toString(36)
        touch(".mobile-fab")
        await("creation opens") { modalOpen() }
        touch("#taskName")
        instrument.sendStringSync(title)
        await("typed title is set") {
            javascript("document.querySelector('#taskName').value === " +
                JSONObject.quote(title)) == "true"
        }
        touch("#taskForm button[type='submit']")
        await("real Android submit touch commits to offline WebView storage") {
            !modalOpen() && taskExists(title)
        }

        // Recreating Android's actual Activity also recreates WebView, so
        // the task must be loaded from the underlying on-device storage.
        scenario.recreate()
        captureWebView()
        await("storage is reloaded after Android Activity recreation") {
            javascript("typeof window.shioriExportBackup === 'function'") == "true" &&
                taskExists(title)
        }
    }
}
