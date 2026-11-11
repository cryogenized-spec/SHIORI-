#!/usr/bin/env python3
"""Automated WCAG A/AA checks for the browser prototype (not a manual audit)."""
import argparse
import functools
import http.server
import json
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
AXE = ROOT / "node_modules" / "axe-core" / "axe.min.js"
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]


def main(report: Path) -> None:
    if not AXE.is_file():
        raise RuntimeError("axe-core not installed; run npm install --no-save --no-package-lock axe-core@4.14.0")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT / "apps" / "web"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    results = {"scanner": "axe-core 4.14.0", "views": {}, "blocking_severities": ["critical", "serious"]}
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                for name, width, height in [("desktop", 1440, 900), ("mobile", 390, 844)]:
                    page = browser.new_page(viewport={"width": width, "height": height})
                    page.goto(f"http://127.0.0.1:{server.server_port}/", wait_until="load")
                    page.locator("#homeCalendar .cal-day").first.wait_for()
                    page.add_script_tag(path=str(AXE))
                    violations = page.evaluate("""async (tags) => {
                        const results = await axe.run(document, {runOnly: {type: 'tag', values: tags}});
                        return results.violations.map(v => ({
                            id: v.id, impact: v.impact, help: v.help,
                            nodes: v.nodes.map(n => n.target).slice(0, 8)
                        }));
                    }""", TAGS)
                    results["views"][name] = violations
                    page.close()
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(results, indent=2) + "\n")
    failures = [(name, violation) for name, vs in results["views"].items()
                for violation in vs if violation["impact"] in results["blocking_severities"]]
    print(json.dumps({"blocking": failures, "report": str(report)}, indent=2))
    if failures:
        raise SystemExit(f"Accessibility gate failed: {len(failures)} serious/critical findings")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, default=Path("accessibility-report.json"))
    main(parser.parse_args().report)
