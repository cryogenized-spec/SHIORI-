#!/usr/bin/env python3
"""Exercise the Android appassets origin without a network or emulator.

This is browser-level validation of the same bundled UI resources the APK loads,
NOT an Android WebView or native-device instrumentation test.
"""
import mimetypes
import shutil
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
ORIGIN = "https://appassets.androidplatform.net"


def run():
    with sync_playwright() as playwright:
        kwargs = {"headless": True}
        binary = shutil.which("chromium") or shutil.which("chromium-browser")
        if binary:
            kwargs.update(executable_path=binary, args=["--no-sandbox"])
        browser = playwright.chromium.launch(**kwargs)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        failures = []
        external_requests = []

        def respond(route):
            request = route.request
            url = request.url
            if not url.startswith(ORIGIN + "/"):
                external_requests.append(url)
                route.abort()
                return
            relative = url[len(ORIGIN) + 1:].split("?", 1)[0]
            path = (WEB / relative).resolve()
            if not path.is_relative_to(WEB) or not path.is_file():
                route.fulfill(status=404, body="")
                return
            mime, _ = mimetypes.guess_type(str(path))
            route.fulfill(
                status=200, body=path.read_bytes(),
                content_type=mime or "application/octet-stream"
            )

        context.route("**/*", respond)
        page = context.new_page()
        page.on("pageerror", lambda error: failures.append(str(error)))
        try:
            page.goto(ORIGIN + "/index.html", wait_until="load")
            page.locator("#mainData").wait_for()
            assert "ANDROID" in page.locator("#footerMode").inner_text()
            assert page.locator("#mainData .task-row").count() == 0
            assert page.evaluate("localStorage.getItem('shiori-demo-tasks')") is None

            # X and Cancel must dismiss an unsubmitted task without writing a
            # record. These real pointer taps previously became unreachable.
            page.locator(".mobile-fab").click()
            page.locator("#taskName").fill("Discard by X")
            page.locator("#taskModal .modal-head [data-close-modal]").click(timeout=4000)
            assert page.locator("#taskModal").is_hidden()
            page.locator(".mobile-fab").click()
            page.locator("#taskName").fill("Discard by Cancel")
            page.locator("#taskModal .modal-actions [data-close-modal]").click(timeout=4000)
            assert page.locator("#taskModal").is_hidden()

            # The native Android Activity dispatches this cancelable event
            # when a hardware/gesture Back reaches the host.
            page.locator(".mobile-fab").click()
            page.locator("#taskName").fill("Discard by Android Back")
            consumed = page.evaluate("""() => {
                const event = new Event('shiori-native-back', {cancelable: true});
                window.dispatchEvent(event);
                return event.defaultPrevented;
            }""")
            assert consumed
            assert page.locator("#taskModal").is_hidden()
            assert page.evaluate("""() => {
                const event = new Event('shiori-native-back', {cancelable: true});
                window.dispatchEvent(event);
                return event.defaultPrevented;
            }""") is False

            # A compressed viewport approximates the visual space left when
            # the on-screen keyboard appears. The X stays tappable.
            page.set_viewport_size({"width": 390, "height": 470})
            page.locator(".mobile-fab").click()
            page.locator("#taskName").fill("Discard with keyboard")
            page.locator("#taskModal .modal-head [data-close-modal]").click(timeout=4000)
            assert page.locator("#taskModal").is_hidden()
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate(
                "JSON.parse(localStorage.getItem('shiori-android-local-tasks') || '[]')"
            ) == []

            # Capture a task, then reopen the Android-origin page and verify
            # the user's record is private to the device storage key.
            page.locator(".mobile-fab").click()
            page.locator("#taskName").fill("Offline field check 栞")
            page.locator("#taskDescription").fill("Works without a server")
            page.locator('#taskForm button[type="submit"]').click()
            assert page.get_by_text("Offline field check 栞").count() >= 1
            stored = page.evaluate(
                "JSON.parse(localStorage.getItem('shiori-android-local-tasks'))"
            )
            assert len(stored) == 1
            assert stored[0]["description"] == "Works without a server"
            assert page.evaluate("localStorage.getItem('shiori-demo-tasks')") is None

            page.reload(wait_until="load")
            assert page.get_by_text("Offline field check 栞").count() >= 1

            page.locator("#mainData [data-detail]").first.click()
            # Even with the inspector open underneath, a creation dialog's
            # close button must receive pointer events rather than the drawer.
            page.evaluate("document.querySelector('.mobile-fab').click()")
            page.locator("#taskModal .modal-head [data-close-modal]").click(timeout=4000)
            assert page.locator("#taskModal").is_hidden()
            assert page.locator("#detailOverlay").is_visible()
            page.locator("#detailPane [data-edit-task]").click()
            page.locator("#editTaskName").fill("Revised offline check 栞")
            page.locator("#editTaskProject").fill("Android local")
            page.locator('#editTaskForm button[type="submit"]').click()
            assert page.locator("#detailPane").get_by_text("Revised offline check 栞").count()
            page.reload(wait_until="load")
            stored = page.evaluate(
                "JSON.parse(localStorage.getItem('shiori-android-local-tasks'))"
            )
            assert stored[0]["title"] == "Revised offline check 栞"
            assert stored[0]["project"] == "Android local"

            # Named views persist independently of task data.
            page.once("dialog", lambda dialog: dialog.accept("Daily queue"))
            page.locator("#saveView").evaluate("(el) => el.click()")
            assert page.locator("#savedViewSelect").input_value() == "Daily queue"
            page.reload(wait_until="load")
            assert page.locator("#savedViewSelect option[value='Daily queue']").count() == 1

            # A deletion should survive another app restart, with no demo
            # records silently reappearing.
            page.locator("#mainData [data-detail]").first.click()
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator("#detailPane [data-remove-task]").click()
            assert page.evaluate(
                "JSON.parse(localStorage.getItem('shiori-android-local-tasks'))"
            ) == []
            page.reload(wait_until="load")
            assert page.locator("#mainData .task-row").count() == 0
            assert not failures, failures
            assert not external_requests, external_requests
            print("Android-origin offline UI: create, edit, persistence, saved views, delete passed")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    run()
