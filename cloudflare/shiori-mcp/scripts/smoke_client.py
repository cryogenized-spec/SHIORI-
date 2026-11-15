#!/usr/bin/env python3
"""Read-only authenticated smoke test for the user's Shiori Cloudflare MCP.
Set SHIORI_MCP_TOKEN in the environment or use --token-file; never log it.
Requires Python 3.10+, stdlib only.
"""
import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UA = "ShioriMCP-Client/0.1 (+https://github.com/cryogenized-spec/SHIORI-)"
BASE = "https://shiori-mcp-alpha.cryogenized.workers.dev"


def request_json(url, body=None, token=None):
    headers = {"User-Agent": UA, "Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    raw = None if body is None else json.dumps(body).encode("utf-8")
    req = Request(url, headers=headers, data=raw, method="POST" if body is not None else "GET")
    try:
        with urlopen(req, timeout=25) as response:
            if response.status != 200:
                raise ValueError(f"Unexpected status: {response.status}")
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} calling {req.full_url} (no credential printed)") from exc


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base", default=BASE, help="User-owned Shiori MCP server URL")
    p.add_argument("--token-file", help="Path to private file with bearer token on last line")
    args = p.parse_args()
    token = os.environ.get("SHIORI_MCP_TOKEN")
    if not token and args.token_file:
        token = Path(args.token_file).read_text(encoding="utf-8").strip().splitlines()[-1].strip()
    if not token:
        p.error("Provide SHIORI_MCP_TOKEN environment variable or --token-file")
    base = args.base.rstrip("/")
    info = request_json(base + "/health")
    assert info["service"] == "shiori-mcp-cloudflare", info
    assert info["service_state"] == "ready", "Cloudflare binding missing"

    def rpc(method, **params):
        resp = request_json(base + "/mcp", {
            "jsonrpc": "2.0", "id": 1, "method": method, "params": params
        }, token)
        assert resp.get("jsonrpc") == "2.0", resp
        if "error" in resp:
            raise RuntimeError(f"MCP error: {resp['error']}")
        return resp["result"]

    initialized = rpc("initialize", protocolVersion="2025-06-18",
                      capabilities={}, clientInfo={"name": "shiori-smoke", "version": "0.1"})
    assert initialized["serverInfo"]["name"] == "shiori-mcp-cloudflare"
    tools = rpc("tools/list")["tools"]
    assert len(tools) == 9, f"Expected 9 alpha tools, got {len(tools)}"
    caps = rpc("tools/call", name="shiori_system_capabilities_read",
               arguments={"workspace_id": "personal"})["structuredContent"]
    assert caps["capabilities"]["local_rust_sync"] is False
    tasks = request_json(base + "/api/v1/ops/tasks.list",
                         {"workspace_id": "personal", "limit": 2}, token)
    assert tasks["ok"] is True
    assert isinstance(tasks["data"]["items"], list)
    print(f"PASS: Worker live, bearer accepted, MCP initialized, {len(tools)} tools registered.")
    print(f"PASS: Remote-only D1 task query returned {len(tasks['data']['items'])} item(s).")
    print("NOTE: This is NOT synchronized with the local Rust database.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (AssertionError, OSError, ValueError, RuntimeError, URLError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
