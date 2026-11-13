#!/usr/bin/env python3
"""Exercise the Android appassets origin without a network or emulator.

This is browser-level validation of the same bundled UI resources the APK loads,
NOT an Android WebView or native-device instrumentation test.
"""
import mimetypes
import json
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
            if url.startswith("shiori-vault://command"):
                # CI has no Kotlin Activity. The protocol is driven by the
                # test below through its exact take/complete functions.
                route.abort()
                return
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
            assert page.evaluate("document.activeElement.matches('.mobile-fab')")

            # A dialog is a keyboard boundary. Shift+Tab from its first
            # control wraps to Save and Tab from Save returns to the X;
            # neither press may focus the underlying task list.
            page.locator(".mobile-fab").click()
            page.locator("#taskModal .modal-head [data-close-modal]").focus()
            page.keyboard.press("Shift+Tab")
            assert page.evaluate(
                "document.activeElement.matches('#taskForm button[type=submit]')"
            )
            page.keyboard.press("Tab")
            assert page.evaluate(
                "document.activeElement.matches('#taskModal .modal-head [data-close-modal]')"
            )
            page.keyboard.press("Escape")
            assert page.locator("#taskModal").is_hidden()
            assert page.evaluate("document.activeElement.matches('.mobile-fab')")

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
            page.locator("#editTaskName").fill("Discarded edit")
            page.keyboard.press("Escape")
            assert page.locator("#editModal").is_hidden()
            assert page.locator("#detailOverlay").is_visible()
            assert page.evaluate(
                "document.activeElement.matches('#detailPane [data-edit-task]')"
            )
            assert page.evaluate(
                "JSON.parse(localStorage.getItem('shiori-android-local-tasks'))"
            )[0]["title"] == "Offline field check 栞"
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

            # Offline backup can roundtrip Unicode records and saved views.
            backup = page.evaluate("window.shioriExportBackup()")
            exported = json.loads(backup)
            assert exported["format"] == "shiori-android-local-v1"
            assert len(exported["tasks"]) == 1
            assert exported["tasks"][0]["title"] == "Revised offline check 栞"
            assert exported["saved_views"][0]["name"] == "Daily queue"

            page.locator(".mobile-fab").click()
            page.locator("#taskName").fill("Temporary second task")
            page.locator('#taskForm button[type="submit"]').click()
            assert len(page.evaluate(
                "JSON.parse(localStorage.getItem('shiori-android-local-tasks'))"
            )) == 2
            assert page.evaluate(
                "(payload) => window.shioriRestoreBackup(payload)", backup
            ) is True
            assert len(page.evaluate(
                "JSON.parse(localStorage.getItem('shiori-android-local-tasks'))"
            )) == 1
            assert page.locator("#savedViewSelect option[value='Daily queue']").count() == 1

            # Bad files must not replace or delete existing on-device records.
            corrupted = json.dumps({
                "format": "shiori-android-local-v1",
                "tasks": [{"title": "<script>unsafe</script>"}],
                "saved_views": [],
            })
            assert page.evaluate(
                "(payload) => window.shioriRestoreBackup(payload)", corrupted
            ) is False
            assert page.evaluate(
                "JSON.parse(localStorage.getItem('shiori-android-local-tasks'))"
            )[0]["title"] == "Revised offline check 栞"

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

            # The canonical Rust migration is opt-in and surfaced only under
            # Android Settings, not executed at startup or by browser tests.
            page.evaluate(
                "document.querySelector('[data-view=settings]').click()"
            )
            assert page.locator("#stageCanonicalShadow").count() == 1
            assert page.locator("#auditCanonicalShadow").count() == 1
            assert page.locator("#openNativeWorkingCopy").count() == 1
            assert page.locator("#openNativeWorkingCopy").is_visible()
            assert page.locator("#exportNativeWorkingCopy").is_visible()
            assert page.locator("#recoverNativeSQLite").is_visible()
            assert page.locator("#inspectNativeSQLiteRecovery").is_visible()
            assert page.locator("#auditNativeMigrationParity").is_visible()
            # Interrupted cutover recovery is an opt-in operation that must
            # never be offered to release or non-debug Android WebViews.
            assert page.locator("#resumeInterruptedNativeCanary").count() == 0
            page.evaluate("""() => {
                window.shioriNativeDebugCanaryAvailable = true;
                document.querySelector('[data-view=settings]').click();
            }""")
            assert page.locator("#resumeInterruptedNativeCanary").is_visible()
            # Native preflight is opt-in; merely opening settings must never
            # create a working DB or mutate legacy WebView localStorage.
            # Both recovery actions are native-only SAF/JNI signals: they
            # cannot access private files or mutate WebView tasks in browser CI.
            assert page.evaluate("localStorage.getItem('shiori-android-local-tasks')") == "[]"
            # SAF export is initiated by Kotlin only; browser tests never
            # receive the private native database or any filesystem path.
            assert page.locator("#auditCanonicalShadow").is_visible()
            # The audit only signals an Android-local custom scheme; never
            # performs a browser-side migration or starts on page load.
            assert page.evaluate("localStorage.getItem(\'shiori-android-local-tasks\')") == "[]"
            assert page.locator("#saveNativeVault").count() == 1
            # The bridge is dormant by default: no startup native mutations.
            assert page.evaluate("window.shioriNativeTakeRequest()") is None
            assert page.locator("#nativeWorkingPanel").count() == 0

            # Simulate the trusted Kotlin host's one-shot request/response
            # handshake. No actual Android runtime or JNI is claimed here.
            page.evaluate("""() => {
                // Kotlin consumes this custom scheme on Android; browser
                // CI simulates Kotlin's take/complete handshake directly.
                window.addEventListener('shiori-native-request', (event) => {
                    event.preventDefault();
                });
                window.shioriNativeBridgeEnabled = true;
                window.shioriNativeWorkingReady();
            }""")
            list_req = page.evaluate("window.shioriNativeTakeRequest()")
            assert list_req is not None
            listed = json.loads(list_req)
            assert listed["protocol"] == "shiori-native-working-v1"
            assert listed["op"] == "list"
            assert page.evaluate("window.shioriNativeTakeRequest()") is None
            assert page.evaluate("""() =>
                window.shioriNativeComplete("9999", JSON.stringify({ok:true}))
            """) is False

            # Native titles are escaped and cannot inject browser markup.
            page.evaluate("""({rid}) => window.shioriNativeComplete(
                rid, JSON.stringify({ok:true,total:1,offset:0,next_offset:null,
                snapshot:"0000000000000001-1",tasks:[{
                    id:"native-1",title:"<img src=x onerror=alert(1)>",
                    project:"Rust",status:"todo",priority:"high",version:2
                }]})
            )""", {"rid":listed["request_id"]})
            page.locator('#nativeWorkingPanel .native-working-row').wait_for()
            assert page.locator("#nativeWorkingPanel img").count() == 0
            assert page.locator("#nativeWorkingPanel").get_by_text(
                "<img src=x onerror=alert(1)>"
            ).count() == 1

            # Task status changes use optimistic revision checks and stay
            # separate from the existing Android WebView local task store.
            page.locator('[data-native-op="status"]').click()
            update_req = json.loads(page.evaluate("window.shioriNativeTakeRequest()"))
            assert update_req["op"] == "status"
            assert update_req["id"] == "native-1"
            assert update_req["expected_version"] == 2
            assert update_req["status"] == "done"
            page.evaluate("""(rid) => window.shioriNativeComplete(
                rid, JSON.stringify({ok:true,task:{
                    id:"native-1",version:3,status:"done"}})
            )""", update_req["request_id"])
            # Successful writes trigger a read-after-write from SQLite.
            refreshed_req = json.loads(
                page.evaluate("window.shioriNativeTakeRequest()")
            )
            assert refreshed_req["op"] == "list"
            page.evaluate("""(rid) => window.shioriNativeComplete(
                rid, JSON.stringify({ok:true,total:1,offset:0,next_offset:null,
                snapshot:"0000000000000002-1",tasks:[{
                    id:"native-1",title:"Native status update",project:"Rust",
                    priority:"high",status:"done",version:3
                }]})
            )""", refreshed_req["request_id"])
            page.get_by_text("Native status update").wait_for()
            assert page.evaluate(
                "localStorage.getItem('shiori-android-local-tasks')"
            ) == "[]"
            assert page.evaluate("localStorage.getItem('shiori-demo-tasks')") is None

            # The read-only source switch renders native SQLite records
            # in SHIORI's familiar task-row layout, without editing either
            # the original WebView array or the separate Rust working copy.
            page.locator("#showNativeReadOnly").click()
            preview_req = json.loads(page.evaluate("window.shioriNativeTakeRequest()"))
            assert preview_req["op"] == "list"
            page.evaluate("""(rid) => window.shioriNativeComplete(
                rid, JSON.stringify({ok:true,total:1,offset:0,next_offset:null,
                snapshot:"0000000000000002-1",tasks:[{
                    id:"native-1",title:"Native preview record",project:"Rust",
                    priority:"high",status:"done",notes:"Only in SQLite",
                    version:3,due_on:null
                }]})
            )""", preview_req["request_id"])
            page.locator("#closeNativeReadOnly").wait_for()
            assert page.get_by_text("Read-only Rust/SQLite source preview").count() == 1
            assert page.locator("#mainData .task-row").count() == 1
            assert page.get_by_text("Native preview record").count() == 1
            assert page.locator("#mainData [data-complete]").count() == 0
            assert page.locator("#mainData [data-detail]").count() == 0
            assert page.locator("#mainData [data-drag]").count() == 0
            assert page.locator("[data-add]").first.is_disabled()
            page.keyboard.press("n")
            assert "open" not in (page.locator("#taskModal").get_attribute("class") or "").split()
            assert page.evaluate("localStorage.getItem('shiori-android-local-tasks')") == "[]"
            # Import callbacks cannot silently restore over legacy data while
            # the view-only native source is displayed.
            assert page.evaluate("""() =>
                window.shioriRestoreBackup(window.shioriExportBackup())
            """) is False
            assert page.evaluate("localStorage.getItem('shiori-android-local-tasks')") == "[]"

            # Explicit return restores the original Android task list and
            # its normal create/edit UI without touching localStorage.
            page.locator("#closeNativeReadOnly").click()
            assert page.locator("#mainData .native-readonly-banner").count() == 0
            assert page.locator("#mainData .task-row").count() == 0
            assert page.locator("[data-add]").first.is_enabled()
            assert page.evaluate("localStorage.getItem('shiori-android-local-tasks')") == "[]"

            # The former >50 hard stop now reads consistent 50+11 pages
            # before showing a complete 61-record source preview.
            page.evaluate("document.querySelector('[data-view=settings]').click()")
            page.locator("#showNativeReadOnly").click()
            large_req = json.loads(page.evaluate("window.shioriNativeTakeRequest()"))
            assert large_req["op"] == "list"
            assert large_req["offset"] == 0
            page.evaluate("""(rid) => window.shioriNativeComplete(rid,
                JSON.stringify({ok:true,total:61,offset:0,next_offset:50,
                snapshot:"aaaaaaaaaaaaaaaa-61",
                tasks:Array.from({length:50},(_,i)=>({
                    id:"n-"+i,title:"Native page "+i,project:"Rust",
                    status:"todo",priority:"medium",version:1
                }))})
            )""", large_req["request_id"])
            continuation = json.loads(page.evaluate("window.shioriNativeTakeRequest()"))
            assert continuation["op"] == "list"
            assert continuation["offset"] == 50
            assert continuation["snapshot"] == "aaaaaaaaaaaaaaaa-61"
            assert page.locator("#mainData .native-readonly-banner").count() == 0
            page.evaluate("""(rid) => window.shioriNativeComplete(rid,
                JSON.stringify({ok:true,total:61,offset:50,next_offset:null,
                snapshot:"aaaaaaaaaaaaaaaa-61",
                tasks:Array.from({length:11},(_,i)=>({
                    id:"n-"+(i+50),title:"Native page "+(i+50),project:"Rust",
                    status:"todo",priority:"medium",version:1
                }))})
            )""", continuation["request_id"])
            page.locator("#closeNativeReadOnly").wait_for()
            assert page.locator("#mainData .task-row").count() == 50
            assert page.get_by_text("Showing 1–50 of 61 matching native records").count() == 1
            page.locator('[data-native-page="next"]').click()
            assert page.locator("#mainData .task-row").count() == 11
            assert page.get_by_text("Native page 60").count() == 1
            page.locator('[data-native-page="prev"]').click()
            assert page.locator("#mainData .task-row").count() == 50
            assert page.evaluate("localStorage.getItem('shiori-android-local-tasks')") == "[]"
            page.locator("#closeNativeReadOnly").click()
            assert page.locator("#mainData .task-row").count() == 0

            # A changed DB between two pages rejects the entire set and
            # never exposes a partial list as a valid source preview.
            page.evaluate("document.querySelector('[data-view=settings]').click()")
            page.locator("#showNativeReadOnly").click()
            stale_first = json.loads(page.evaluate("window.shioriNativeTakeRequest()"))
            page.evaluate("""(rid) => window.shioriNativeComplete(rid,
                JSON.stringify({ok:true,total:61,offset:0,next_offset:50,
                snapshot:"bbbbbbbbbbbbbbbb-61",
                tasks:Array.from({length:50},(_,i)=>({
                    id:"old-"+i,title:"Stale "+i,project:"Rust",
                    status:"todo",priority:"low",version:1
                }))})
            )""", stale_first["request_id"])
            stale_next = json.loads(page.evaluate("window.shioriNativeTakeRequest()"))
            assert stale_next["offset"] == 50
            assert stale_next["snapshot"] == "bbbbbbbbbbbbbbbb-61"
            page.evaluate("""(rid) => window.shioriNativeComplete(rid,
                JSON.stringify({ok:true,total:61,offset:50,next_offset:null,
                snapshot:"cccccccccccccccc-61",tasks:[{
                    id:"old-50",title:"Changed source",project:"Rust",
                    status:"todo",priority:"low",version:2
                }]})
            )""", stale_next["request_id"])
            page.get_by_text("Native tasks changed during paging", exact=False).wait_for()
            assert page.locator("#mainData .native-readonly-banner").count() == 0
            assert page.locator("#nativeWorkingPanel .native-working-row").count() == 0
            assert page.evaluate("localStorage.getItem('shiori-android-local-tasks')") == "[]"

            # Source selection is not saved or resumed on a new app launch.
            page.reload(wait_until="load")
            assert page.locator("#mainData .native-readonly-banner").count() == 0
            assert page.evaluate("window.shioriNativeTakeRequest()") is None

            assert not failures, failures
            assert not external_requests, external_requests
            print("Android-origin offline UI: create, edit, persistence, saved views, delete passed")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    run()
