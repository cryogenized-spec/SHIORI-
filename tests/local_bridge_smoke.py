#!/usr/bin/env python3
"""End-to-end localhost HTTP -> compiled Rust CLI -> SQLite smoke test."""
import argparse
import http.client
import json
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps"))
from local_bridge import make_server  # noqa: E402


def exercise(cli):
    with tempfile.TemporaryDirectory(prefix="shiori-bridge-") as folder:
        database = Path(folder) / "tasks.sqlite3"
        server = make_server(0, cli, database)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_port
            host = f"127.0.0.1:{port}"
            def request(method, path, payload=None, **override):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
                data = json.dumps(payload).encode() if payload is not None else None
                headers = {"Host": host, "Origin": f"http://{host}",
                           "Content-Type": "application/json"}
                headers.update(override)
                conn.request(method, path, body=data, headers=headers)
                response = conn.getresponse()
                body = response.read()
                status = response.status
                conn.close()
                return status, json.loads(body) if path.startswith("/api") else body

            assert request("GET", "/api/health") == (
                200, {"mode": "rust-sqlite", "protocol": 1}
            )
            assert request("GET", "/api/tasks") == (200, {"tasks": []})
            status, html = request("GET", "/")
            assert status == 200 and b'id="footerMode"' in html
            status, js = request("GET", "/app.js")
            assert status == 200 and b"bootstrapBridge" in js

            assert request("POST", "/api/tasks", {
                "title": "Build the local bridge",
                "project": "SHIORI", "priority": "high",
                "notes": "A line\nand another 栞",
                "due_on": "2026-11-12",
                "estimate_minutes": 45
            }) == (201, {"ok": True})
            status, snapshot = request("GET", "/api/tasks")
            assert status == 200 and len(snapshot["tasks"]) == 1, snapshot
            task = snapshot["tasks"][0]
            assert task["notes"] == "A line\nand another 栞"
            assert task["estimate_minutes"] == 45
            assert task["due_on"] == "2026-11-12"
            assert task["status"] == "todo"
            assert task["version"] == 1
            task_id = task["id"]

            assert request("POST", f"/api/tasks/{task_id}/status",
                           {"status": "in_progress"}) == (200, {"ok": True})
            status, snapshot = request("GET", "/api/tasks")
            assert snapshot["tasks"][0]["status"] == "in_progress"
            assert snapshot["tasks"][0]["version"] == 2
            assert request("POST", f"/api/tasks/{task_id}/status",
                           {"status": "done"}) == (200, {"ok": True})
            assert request("GET", "/api/tasks")[1]["tasks"][0]["status"] == "done"

            # Mutating requests require a matching local Origin; DNS-rebinding
            # hostnames and form content types cannot change task records.
            assert request(
                "POST", "/api/tasks", {"title": "Injected"},
                Origin="http://untrusted.invalid"
            )[0] == 403
            assert request(
                "POST", "/api/tasks", {"title": "Injected"},
                Host="attacker.invalid"
            )[0] == 403
            assert request(
                "POST", "/api/tasks", {"title": "Injected"},
                **{"Content-Type": "text/plain"}
            )[0] == 415
            assert request("POST", "/api/tasks", {"title": "   "})[0] == 400
            assert request("GET", "/api/tasks")[1]["tasks"][0]["id"] == task_id
            assert len(request("GET", "/api/tasks")[1]["tasks"]) == 1
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=4)

        # The web adapter never stores task data itself: reopening the Rust DB
        # via a new server keeps identity, status, notes, estimate and revision.
        again = make_server(0, cli, database)
        worker = threading.Thread(target=again.serve_forever, daemon=True)
        worker.start()
        try:
            conn = http.client.HTTPConnection("127.0.0.1", again.server_port, timeout=15)
            conn.request("GET", "/api/tasks", headers={
                "Host": f"127.0.0.1:{again.server_port}"
            })
            response = conn.getresponse()
            assert response.status == 200
            stored = json.loads(response.read())["tasks"]
            conn.close()
            assert stored[0]["id"] == task_id
            assert stored[0]["status"] == "done"
            assert stored[0]["version"] == 3
            assert stored[0]["estimate_minutes"] == 45
        finally:
            again.shutdown()
            again.server_close()
            worker.join(timeout=4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--cli", required=True, type=Path)
    args = parser.parse_args()
    exercise(args.cli)
    print("Local Rust/SQLite HTTP bridge: all smoke checks passed")
