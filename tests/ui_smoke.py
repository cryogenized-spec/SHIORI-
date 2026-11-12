#!/usr/bin/env python3
"""Headless Chromium end-to-end smoke/performance test of the browser prototype.

Uses synthetic demo tasks only. The report remains local or in CI artifacts; this
is NOT production telemetry and never contains a user's real task data.
"""
import argparse
import functools
import http.server
import json
import shutil
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def run(report: Path):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "apps" / "web"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/"
    results = {"schema": 1, "kind": "prototype_browser_smoke", "views": {}}
    try:
        with sync_playwright() as playwright:
            # Use the preinstalled Chromium locally; CI uses Playwright Chromium.
            kwargs = {"headless": True}
            binary = shutil.which("chromium") or shutil.which("chromium-browser")
            if binary:
                kwargs["executable_path"] = binary
                kwargs["args"] = ["--no-sandbox"]
            browser = playwright.chromium.launch(**kwargs)
            try:
                for label, width, height in (("desktop", 1440, 900), ("mobile", 390, 844)):
                    page = browser.new_page(viewport={"width": width, "height": height})
                    failures = []
                    page.on("pageerror", lambda exc: failures.append(str(exc)))
                    page.goto(url, wait_until="load")
                    page.locator("#homeCalendar .cal-day").first.wait_for()
                    require(page.locator("#homeCalendarToggle").get_attribute("aria-expanded") == "true", "Calendar not visible initially")
                    require(page.locator("#homeCalendar .cal-day").count() >= 28, "Calendar day cells missing")

                    # Calendar toggle is usable and the preference survives refresh.
                    page.locator("#homeCalendarToggle").click()
                    require(page.locator("#homeCalendar").is_hidden(), "Calendar did not collapse")
                    page.reload(wait_until="load")
                    require(page.locator("#homeCalendar").is_hidden(), "Calendar preference was not persisted")
                    page.locator("#homeCalendarToggle").click()
                    require(page.locator("#homeCalendar .cal-day").count() >= 28, "Calendar did not reopen")

                    before = page.locator("#homeCalendar h3").inner_text()
                    page.locator('[data-calendar-shift="1"]').click()
                    require(page.locator("#homeCalendar h3").inner_text() != before, "Month navigation did not advance")
                    page.locator("[data-calendar-today]").click()
                    require(page.locator("#homeCalendar h3").inner_text() == before, "Today did not return to current month")

                    # Task creation, list rendering and local persistence.
                    add = page.locator(".mobile-fab") if label == "mobile" else page.locator(".desktop-add")
                    add.click()
                    page.locator("#taskName").fill("SHIORI browser regression test")
                    page.locator('#taskForm button[type="submit"]').click()
                    page.locator("#searchInput").fill("SHIORI browser regression test")
                    require(page.locator("#mainData").get_by_text("SHIORI browser regression test").count() >= 1, "Created task not displayed")
                    page.reload(wait_until="load")
                    # Reload resets the view to Today; sample task is due today.
                    require(page.get_by_text("SHIORI browser regression test").count() >= 1, "Task not persisted across reload")

                    # M2 attention is explicitly local-only: do not imply
                    # assignment tracking or a synced attention inbox.
                    page.evaluate("""() => document.querySelector('#mainNav [data-view="attention"]').click()""")
                    require(page.locator(".attention-note").count() == 1,
                            "Local attention limitation was not shown")
                    require(page.locator("#mainData .task-row").count() > 0,
                            "Attention view unexpectedly empty")

                    # Saved FIFO choice should survive a reload on mobile and desktop.
                    page.evaluate("""() => {
                      const el = document.querySelector('#sortMode');
                      el.value = 'fifo';
                      el.dispatchEvent(new Event('change', {bubbles: true}));
                    }""")
                    page.reload(wait_until="load")
                    require(page.locator("#sortMode").input_value() == "fifo",
                            "Task-order preference was not persisted")
                    require(page.locator("#homeCalendarToggle").get_attribute("aria-expanded") == "true",
                            "Returning to My day should preserve expanded calendar")

                    # Measure synchronous render work rather than round-trip CDP click overhead.
                    render_times = page.evaluate("""() => {
                      const button = document.querySelector('#homeCalendarToggle');
                      const times = [];
                      for (let i = 0; i < 40; i++) {
                        const started = performance.now(); button.click();
                        times.push(performance.now() - started);
                      }
                      return times.sort((a,b) => a-b);
                    }""")
                    perf = page.evaluate("""() => {
                      const nav = performance.getEntriesByType('navigation')[0];
                      return {dom_content_loaded_ms: nav.domContentLoadedEventEnd,
                        load_ms: nav.loadEventEnd, scripts: performance.getEntriesByType('resource')
                        .filter(x => x.name.endsWith('/app.js')).length};
                    }""")
                    require(perf["load_ms"] < 1500, f"Browser page load exceeded 1500ms: {perf['load_ms']:.2f}")
                    require(perf["scripts"] == 1, "Expected exactly one application script")
                    widths = page.evaluate("""() => ({width: document.documentElement.scrollWidth,
                      viewport: document.documentElement.clientWidth})""")
                    require(widths["width"] <= widths["viewport"] + 2, f"Horizontal overflow at {width}px: {widths}")
                    require(not failures, f"Browser script errors at {width}px: {failures}")
                    require(render_times[37] < 150, f"Calendar interaction p95 exceeded 150 ms: {render_times[37]:.2f}")
                    results["views"][label] = {**perf, "calendar_toggle_p95_ms": round(render_times[37], 3),
                                                "horizontal_overflow_px": max(0, widths["width"] - widths["viewport"])}
                    page.close()
                browser.close()
            finally:
                if browser.is_connected():
                    browser.close()
    finally:
        server.shutdown()
        server.server_close()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("browser-metrics.json"))
    run(parser.parse_args().report)
