#!/usr/bin/env python3
"""Development-only localhost adapter: browser -> Rust CLI -> SQLite.

Not a production REST/MCP endpoint, remote server or authentication boundary.
The CLI owns all task mutations; this module never opens SQLite directly.
"""
import argparse
import json
import re
import struct
import subprocess
from datetime import date, datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "apps" / "web"
MAGIC = b"SHIORI-BRIDGE-2\n"
ATTENTION_MAGIC = b"SHIORI-ATTENTION-1\n"
FIELDS = ("id", "title", "notes", "project", "priority", "status",
          "due_on", "created_at", "updated_at", "estimate_minutes",
          "version", "assignee_id")
ATTENTION_FIELDS = FIELDS + ("blocked",)
UUID = re.compile(r"^[a-fA-F0-9-]{36}$")
MAX_BODY = 8192
MAX_EXPORT = 16 * 1024 * 1024


class RevisionConflict(ValueError):
    """The submitted revision is no longer current."""


def valid_version(value):
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        raise ValueError("a valid expected_version is required")
    return value


def valid_fields(data):
    """Validate the editable snapshot and return safe CLI flag values."""
    title = data.get("title")
    project = data.get("project")
    notes = data.get("notes")
    priority = data.get("priority")
    due = data.get("due_on")
    minutes = data.get("estimate_minutes")
    if not isinstance(title, str) or not 0 < len(title.strip()) <= 120:
        raise ValueError("invalid title")
    if not isinstance(project, str) or not 0 < len(project.strip()) <= 160:
        raise ValueError("invalid project")
    if not isinstance(notes, str) or len(notes) > 6000:
        raise ValueError("invalid notes")
    if priority not in ("low", "medium", "high", "urgent"):
        raise ValueError("invalid priority")
    if due is not None:
        if not isinstance(due, str) or date.fromisoformat(due).isoformat() != due:
            raise ValueError("invalid due date")
    if minutes is not None and (
        type(minutes) is not int or not 1 <= minutes <= 1440
    ):
        raise ValueError("invalid estimate")
    return title.strip(), project.strip(), notes, priority, due, minutes


def decode_snapshot(data, marker=MAGIC, columns=FIELDS):
    """Fail closed if a CLI/API version changes the machine protocol."""
    if len(data) > MAX_EXPORT or not data.startswith(marker):
        raise ValueError("unexpected Rust task snapshot format")
    rows, offset = [], len(marker)
    while offset < len(data):
        values = []
        for _ in columns:
            if offset + 4 > len(data):
                raise ValueError("truncated record header")
            size = struct.unpack_from(">I", data, offset)[0]
            offset += 4
            if size > MAX_EXPORT or offset + size > len(data):
                raise ValueError("truncated or oversized record field")
            values.append(data[offset:offset + size].decode("utf-8"))
            offset += size
        task = dict(zip(columns, values))
        task["estimate_minutes"] = (int(task["estimate_minutes"])
                                    if task["estimate_minutes"] else None)
        task["version"] = int(task["version"])
        task["due_on"] = task["due_on"] or None
        task["assignee_id"] = task["assignee_id"] or None
        if "blocked" in task:
            if task["blocked"] not in ("true", "false"):
                raise ValueError("invalid blocked state")
            task["blocked"] = task["blocked"] == "true"
        rows.append(task)
    return rows


def make_server(port, cli, database):
    """Bind solely to loopback and serve static UI plus strictly scoped routes."""
    cli = Path(cli).expanduser().resolve()
    if not cli.is_file():
        raise FileNotFoundError(f"Build the Rust CLI first: {cli}")
    database = Path(database).expanduser().resolve() if database else None

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(WEB), **kwargs)

        def end_headers(self):
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; img-src 'self' data:; "
                "script-src 'self'; style-src 'self' 'unsafe-inline'; "
                "connect-src 'self'; frame-ancestors 'none'",
            )
            super().end_headers()

        def response(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def host_allowed(self):
            # Reject DNS-rebinding hostnames even though the socket is local.
            return self.headers.get("Host", "") in {
                f"127.0.0.1:{self.server.server_port}",
                f"localhost:{self.server.server_port}",
            }

        def run_cli(self, *arguments):
            args = [str(cli)]
            if database is not None:
                args.extend(["--database", str(database)])
            args.extend(arguments)
            result = subprocess.run(
                args, capture_output=True, timeout=15, check=False
            )
            if result.returncode:
                if b"RevisionConflict" in result.stderr or b"task was changed by another writer" in result.stderr:
                    raise RevisionConflict("task was changed; reload before saving")
                raise ValueError("Rust task command was rejected")
            if len(result.stdout) > MAX_EXPORT:
                raise ValueError("task snapshot exceeds local bridge limit")
            return result.stdout

        def do_GET(self):
            if not self.host_allowed():
                self.response(403, {"error": "invalid Host"})
                return
            path = urlsplit(self.path).path
            if path == "/api/health":
                self.response(200, {"mode": "rust-sqlite", "protocol": 1})
            elif path == "/api/tasks":
                try:
                    self.response(200, {"tasks": decode_snapshot(self.run_cli("bridge-dump"))})
                except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                    self.log_error("Rust read failed: %s", type(exc).__name__)
                    self.response(503, {"error": "local Rust storage unavailable"})
            elif path == "/api/attention":
                try:
                    records = decode_snapshot(
                        self.run_cli("bridge-attention"),
                        ATTENTION_MAGIC, ATTENTION_FIELDS
                    )
                    self.response(200, {
                        "tasks": records,
                        "local_identity": "local",
                        "fresh_at": datetime.now(timezone.utc).isoformat(),
                    })
                except (ValueError, OSError, subprocess.TimeoutExpired) as exc:
                    self.log_error("Attention query failed: %s", type(exc).__name__)
                    self.response(503, {"error": "local Rust attention unavailable"})
            elif path.startswith("/api/"):
                self.response(404, {"error": "unknown API route"})
            else:
                super().do_GET()

        def do_POST(self):
            if not self.host_allowed():
                self.response(403, {"error": "invalid Host"})
                return
            origin = self.headers.get("Origin", "")
            host = self.headers.get("Host", "")
            if origin != f"http://{host}":
                self.response(403, {"error": "same-origin request required"})
                return
            if self.headers.get_content_type() != "application/json":
                self.response(415, {"error": "JSON content type required"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= MAX_BODY:
                    raise ValueError("invalid request size")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("JSON object expected")
                path = urlsplit(self.path).path
                if path == "/api/tasks":
                    title = data.get("title")
                    project = data.get("project", "Inbox")
                    priority = data.get("priority", "medium")
                    notes = data.get("notes", "")
                    due = data.get("due_on")
                    minutes = data.get("estimate_minutes")
                    if not isinstance(title, str) or not 0 < len(title.strip()) <= 160:
                        raise ValueError("invalid task title")
                    if not isinstance(project, str) or not 0 < len(project.strip()) <= 160:
                        raise ValueError("invalid project")
                    if not isinstance(notes, str) or len(notes) > 6000:
                        raise ValueError("invalid notes")
                    if priority not in ("low", "medium", "high", "urgent"):
                        raise ValueError("invalid priority")
                    cmd = ["add", title.strip(), "--project", project.strip(),
                           "--priority", priority, "--notes", notes]
                    if due is not None:
                        if not isinstance(due, str) or date.fromisoformat(due).isoformat() != due:
                            raise ValueError("invalid due date")
                        cmd.extend(["--due", due])
                    if minutes is not None:
                        if type(minutes) is not int or not 1 <= minutes <= 1440:
                            raise ValueError("invalid estimate")
                        cmd.extend(["--minutes", str(minutes)])
                    self.run_cli(*cmd)
                    self.response(201, {"ok": True})
                    return
                match = re.fullmatch(r"/api/tasks/([^/]+)/status", path)
                if match:
                    identifier = match.group(1)
                    status = data.get("status")
                    if not UUID.fullmatch(identifier):
                        raise ValueError("invalid task ID")
                    if status not in ("todo", "in_progress", "done"):
                        raise ValueError("invalid status")
                    self.run_cli("status", identifier, status)
                    self.response(200, {"ok": True})
                    return
                edit = re.fullmatch(r"/api/tasks/([^/]+)/(edit|delete)", path)
                if edit:
                    identifier, action = edit.groups()
                    if not UUID.fullmatch(identifier):
                        raise ValueError("invalid task ID")
                    revision = valid_version(data.get("expected_version"))
                    if action == "delete":
                        if set(data) != {"expected_version"}:
                            raise ValueError("delete accepts only expected_version")
                        self.run_cli(
                            "remove", identifier, "--if-version", str(revision)
                        )
                        self.response(200, {"ok": True})
                        return
                    edit_fields = {
                        "title", "project", "notes", "priority",
                        "due_on", "estimate_minutes", "expected_version"
                    }
                    if set(data) not in (edit_fields, edit_fields | {"assignee_id"}):
                        raise ValueError("edit requires the complete task snapshot")
                    title, project, notes, priority, due, minutes = valid_fields(data)
                    command = [
                        "edit", identifier, "--if-version", str(revision),
                        "--title", title, "--notes", notes,
                        "--project", project, "--priority", priority,
                    ]
                    if due is None:
                        command.append("--clear-due")
                    else:
                        command.extend(["--due", due])
                    if minutes is None:
                        command.append("--clear-minutes")
                    else:
                        command.extend(["--minutes", str(minutes)])
                    if "assignee_id" in data:
                        assignee = data["assignee_id"]
                        if assignee is None:
                            command.append("--unassign")
                        elif isinstance(assignee, str) and re.fullmatch(
                            r"[A-Za-z0-9._:-]{1,64}", assignee
                        ):
                            command.extend(["--assign-to", assignee])
                        else:
                            raise ValueError("invalid assignee ID")
                    self.run_cli(*command)
                    self.response(200, {"ok": True})
                    return
                self.response(404, {"error": "unknown API route"})
            except RevisionConflict as exc:
                self.response(409, {"error": str(exc)})
            except (ValueError, TypeError, OverflowError) as exc:
                self.response(400, {"error": str(exc)[:140]})
            except (OSError, subprocess.TimeoutExpired):
                self.response(503, {"error": "local Rust storage unavailable"})

        def do_OPTIONS(self):
            self.response(405, {"error": "cross-origin requests are not supported"})

    # No LAN/WAN binding option. No credentials, API keys or remote services.
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description="SHIORI local development bridge")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--database", help="SQLite database path (CLI default if omitted)")
    parser.add_argument(
        "--cli", default=str(ROOT / "target" / "debug" / "shiori-cli"),
        help="Path to the compiled local Rust CLI",
    )
    args = parser.parse_args()
    with make_server(args.port, args.cli, args.database) as server:
        print(f"SHIORI local bridge: http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever(poll_interval=0.1)


if __name__ == "__main__":
    main()
