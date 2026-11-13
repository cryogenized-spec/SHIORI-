#!/usr/bin/env python3
"""M2.3 simulated Android host: original and Rust task sources never mix.

Exercises browser-origin UI + typed, fake Kotlin bridge. This does NOT
constitute a physical-device or Android instrumentation test.
"""
import json
import mimetypes
import shutil
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
ORIGIN = "https://appassets.androidplatform.net"


def main():
    with sync_playwright() as playwright:
        args = {"headless": True}
        binary = shutil.which("chromium") or shutil.which("chromium-browser")
        if binary:
            args.update(executable_path=binary, args=["--no-sandbox"])
        browser = playwright.chromium.launch(**args)
        context = browser.new_context(viewport={"width": 390, "height": 844})
        failures = []
        outgoing = []

        def serve(route):
            url = route.request.url
            if not url.startswith(ORIGIN + "/"):
                outgoing.append(url)
                route.abort()
                return
            name = url[len(ORIGIN) + 1:].split("?", 1)[0]
            path = (WEB / name).resolve()
            if not path.is_relative_to(WEB) or not path.is_file():
                route.fulfill(status=404, body="")
                return
            mime, _ = mimetypes.guess_type(str(path))
            route.fulfill(status=200, body=path.read_bytes(),
                          content_type=mime or "application/octet-stream")

        context.route("**/*", serve)
        page = context.new_page()
        page.on("pageerror", lambda error: failures.append(str(error)))

        def take():
            for _ in range(20):
                raw = page.evaluate("window.shioriNativeTakeRequest()")
                if raw is not None:
                    return json.loads(raw)
                page.wait_for_timeout(25)
            raise AssertionError("native source did not issue a bridge request")

        def complete(request, reply):
            accepted = page.evaluate(
                """({id,reply})=>window.shioriNativeComplete(
                    id, JSON.stringify(reply)
                )""",
                {"id": request["request_id"], "reply": reply},
            )
            assert accepted

        metadata = {
            "saved_views": [],
            "sort": "focus",
            "revision": 1,
            "tags_by_id": {"native-1": ["Stored", "SQLite"]},
        }

        def supply_full_read(title="Native canonical task", version=4):
            first = take()
            assert first["op"] == "metadata", first
            assert first["source"] == "primary"
            complete(first, {"ok": True, "metadata": metadata})
            listed = take()
            assert listed["op"] == "list"
            assert listed["offset"] == 0
            complete(listed, {
                "ok": True, "total": 1, "offset": 0,
                "next_offset": None, "snapshot": f"{version:016x}-1",
                "tasks": [{
                    "id": "native-1", "title": title, "notes": "Canonical description",
                    "project": "Core", "priority": "high", "status": "todo",
                    "version": version, "due_on": None, "estimate_minutes": 35,
                    "assignee_id": "local",
                    "created_at": "2026-11-12T10:00:00Z",
                    "updated_at": "2026-11-13T10:00:00Z",
                }],
            })

        try:
            page.goto(ORIGIN + "/index.html", wait_until="load")
            old = [{
                "id": "legacy-1", "title": "Original WebView task",
                "description": "Do not change", "project": "Android",
                "priority": "medium", "status": "todo", "due": "",
                "tags": ["Original"], "mins": 25, "version": 2,
            }]
            page.evaluate(
                "(rows)=>localStorage.setItem('shiori-android-local-tasks', JSON.stringify(rows))",
                old,
            )
            page.evaluate("""() => {
                localStorage.setItem('shiori-demo-sort', 'fifo');
                localStorage.setItem('shiori-saved-views', JSON.stringify([
                    {name:'Legacy only',view:'inbox',filter:'all',sort:'fifo',query:''}
                ]));
            }""")
            page.reload(wait_until="load")
            legacy_sort = page.evaluate("localStorage.getItem('shiori-demo-sort')")
            legacy_views = page.evaluate("localStorage.getItem('shiori-saved-views')")
            baseline = page.evaluate(
                "localStorage.getItem('shiori-android-local-tasks')"
            )
            assert "Original WebView task" in baseline
            frozen = page.evaluate("window.shioriFreezeLegacyForCutover()")
            assert json.loads(frozen)["tasks"][0]["title"] == "Original WebView task"
            assert page.locator("[data-add]").first.is_disabled()
            assert page.evaluate("window.shioriRestoreBackup(window.shioriExportBackup())") is False
            page.evaluate("window.shioriAbortCutover()")
            assert page.locator("[data-add]").first.is_enabled()

            page.evaluate("""() => {
                window.shioriNativeBridgeEnabled = true;
                window.addEventListener('shiori-native-request', event => {
                    event.preventDefault();
                });
                window.shioriNativeActivate();
            }""")
            supply_full_read()
            page.get_by_text("Experimental Rust task source").wait_for()
            page.evaluate("document.querySelector('[data-view=inbox]').click()")
            assert page.get_by_text("Native canonical task").count() == 1
            assert page.get_by_text("Original WebView task").count() == 0
            assert "Stored / SQLite" in page.locator("#mainData").inner_text()
            assert page.evaluate(
                "localStorage.getItem('shiori-android-local-tasks')"
            ) == baseline

            # Edit in the normal task UI must issue a revision-checked native
            # operation, never WebView save().
            page.locator('#mainData [data-detail="native-1"]').first.click()
            page.locator("[data-edit-task]").click()
            page.locator("#editTaskName").fill("Edited through Rust")
            page.locator("#editTaskDescription").fill("Changed description")
            page.locator("#editTaskForm").evaluate("(form)=>form.requestSubmit()")
            edited = take()
            assert edited["op"] == "edit"
            assert edited["source"] == "primary"
            assert edited["id"] == "native-1"
            assert edited["expected_version"] == 4
            assert edited["notes"] == "Changed description"
            complete(edited, {"ok": True, "task": {"id": "native-1", "version": 5}})
            supply_full_read("Edited through Rust", 5)
            page.get_by_text("Edited through Rust").first.wait_for()
            assert page.evaluate(
                "localStorage.getItem('shiori-android-local-tasks')"
            ) == baseline

            # Tags are edited separately, atomically, with the currently
            # displayed canonical task revision. Neither task edits nor tag
            # edits should write to the frozen WebView JSON snapshot.
            page.locator("#nativeDetailTagInput").fill("Native, Quality, 栞")
            page.locator("#nativeDetailTagsForm").evaluate(
                "(form)=>form.requestSubmit()"
            )
            tag_request = take()
            assert tag_request["op"] == "tags_set", tag_request
            assert tag_request["expected_version"] == 5
            assert tag_request["tags"] == ["Native", "Quality", "栞"]
            complete(tag_request, {"ok": True, "id": "native-1", "version": 6,
                                   "tags": ["Native", "Quality", "栞"]})
            metadata["tags_by_id"]["native-1"] = ["Native", "Quality", "栞"]
            supply_full_read("Edited through Rust", 6)
            assert page.locator("#nativeDetailTagInput").input_value() == "Native, Quality, 栞"
            assert page.evaluate(
                "localStorage.getItem('shiori-android-local-tasks')"
            ) == baseline

            # Native version-checked completion, again no legacy write.
            page.evaluate(
                "document.querySelector('[data-view=inbox]').click()"
            )
            # The detail overlay remains open after an edit. Use its
            # completion control, which is the actual tappable user surface.
            page.locator("#detailOverlay [data-complete]").click()
            completed = take()
            assert completed["op"] == "status"
            assert completed["expected_version"] == 6
            assert completed["status"] == "done"
            complete(completed, {"ok": True, "task": {"id": "native-1", "version": 7}})
            supply_full_read("Edited through Rust", 7)
            assert page.evaluate(
                "localStorage.getItem('shiori-android-local-tasks')"
            ) == baseline

            # Both native sorting and saved views are SQLite-owned; the
            # untouched WebView legacy preferences are not mutated.
            page.locator("#sortMode").select_option("priority")
            sort_request = take()
            assert sort_request["op"] == "workspace_set", sort_request
            assert sort_request["expected_revision"] == 1
            assert sort_request["sort"] == "priority"
            metadata["sort"] = "priority"
            metadata["revision"] = 2
            complete(sort_request, {"ok": True, "metadata": metadata})
            supply_full_read("Edited through Rust", 7)
            assert page.locator("#sortMode").input_value() == "priority"
            assert page.evaluate("localStorage.getItem('shiori-demo-sort')") == legacy_sort

            page.once("dialog", lambda dialog: dialog.accept("Native review"))
            page.locator("#saveView").evaluate("(button)=>button.click()")
            view_request = take()
            assert view_request["op"] == "workspace_set", view_request
            assert view_request["expected_revision"] == 2
            assert view_request["saved_views"][0]["name"] == "Native review"
            metadata["saved_views"] = view_request["saved_views"]
            metadata["revision"] = 3
            complete(view_request, {"ok": True, "metadata": metadata})
            supply_full_read("Edited through Rust", 7)
            assert page.locator(
                "#savedViewSelect option[value='Native review']"
            ).count() == 1
            assert page.evaluate("localStorage.getItem('shiori-saved-views')") == legacy_views

            page.locator("#savedViewSelect").select_option("Native review")
            page.locator("#removeView").click()
            remove_request = take()
            assert remove_request["op"] == "workspace_set", remove_request
            assert remove_request["expected_revision"] == 3
            assert remove_request["saved_views"] == []
            metadata["saved_views"] = []
            metadata["revision"] = 4
            complete(remove_request, {"ok": True, "metadata": metadata})
            supply_full_read("Edited through Rust", 7)
            assert page.locator(
                "#savedViewSelect option[value='Native review']"
            ).count() == 0
            assert page.evaluate("localStorage.getItem('shiori-saved-views')") == legacy_views

            # The native source is locked while Android validates the
            # independent rollback vault. No WebView write or new native
            # mutation can be issued during the comparison.
            frozen = page.evaluate("window.shioriNativeFreezeForRollback()")
            assert json.loads(frozen)["tasks"][0]["title"] == "Original WebView task"
            assert page.locator("[data-add]").first.is_disabled()
            assert page.evaluate("window.shioriNativeFreezeForRollback()") is None
            assert page.evaluate(
                "localStorage.getItem('shiori-android-local-tasks')"
            ) == baseline
            page.evaluate("window.shioriAbortCutover()")
            assert page.locator("[data-add]").first.is_enabled()

            # Explicit rollback reloads only the untouched legacy store.
            assert page.evaluate("window.shioriNativeFreezeForRollback()")
            assert page.evaluate("window.shioriNativeDeactivate()") is True
            page.evaluate("document.querySelector('[data-view=inbox]').click()")
            assert page.get_by_text("Original WebView task").count() == 1
            assert page.get_by_text("Edited through Rust").count() == 0
            assert page.locator("#sortMode").input_value() == "fifo"
            assert page.locator("#savedViewSelect option[value='Legacy only']").count() == 1

            # Rollback during an in-flight native metadata read must invalidate
            # that response rather than rendering native records afterwards.
            # Launch without awaiting the returned Promise: this mock host
            # must answer metadata while the native loader is still pending.
            page.evaluate("() => { window.shioriNativeActivate(); }")
            interrupted = take()
            assert interrupted["op"] == "metadata"
            assert page.evaluate("window.shioriNativeDeactivate()") is True
            assert page.evaluate(
                """({id,metadata})=>window.shioriNativeComplete(
                    id, JSON.stringify({ok:true,metadata})
                )""",
                {"id": interrupted["request_id"], "metadata": metadata},
            ) is False
            page.evaluate("document.querySelector('[data-view=inbox]').click()")
            assert page.get_by_text("Original WebView task").count() == 1
            assert page.evaluate("window.shioriNativeTakeRequest()") is None
            assert page.evaluate(
                "localStorage.getItem('shiori-android-local-tasks')"
            ) == baseline

            # Native source failure must never fall back silently to legacy.
            page.evaluate("window.shioriNativeUnavailable()")
            page.get_by_text("Rust task source unavailable").wait_for()
            assert page.get_by_text("Original WebView task").count() == 0
            assert page.locator("[data-add]").first.is_disabled()
            assert page.evaluate(
                "localStorage.getItem('shiori-android-local-tasks')"
            ) == baseline
            page.evaluate("window.shioriNativeDeactivate()")

            assert not failures, failures
            assert not outgoing, outgoing
            print("M2.4d browser-origin canary: verified Rust tags, views, ordering and legacy isolation")
        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
