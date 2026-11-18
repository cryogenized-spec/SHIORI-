#!/usr/bin/env python3
"""Regenerate Shiori's self-contained MCP schema catalog from docs/api.

The Worker is deployed as a standalone module. A fully bundled, generated
snapshot avoids a runtime dependency on the repository's documentation.
This script edits only the catalog constant inside src/worker.js.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "docs/api/operations.v1.json"
TARGET = ROOT / "cloudflare/shiori-mcp/src/worker.js"
PATTERN = re.compile(r"(?m)^const SCHEMA_CATALOG=(.+);$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if the embedded registry is out of date")
    args = parser.parse_args()
    registry = json.loads(SOURCE.read_text(encoding="utf-8"))
    if len(registry.get("operations", [])) != 124:
        raise SystemExit("Unexpected catalog size; review operation registry changes before regenerating")
    text = TARGET.read_text(encoding="utf-8")
    match = PATTERN.search(text)
    if match is None:
        raise SystemExit("Missing embedded registry in Worker")
    current = json.loads(match.group(1))
    if args.check:
        if current != registry:
            raise SystemExit("Schema catalog drift: run sync_operation_catalog.py")
        print("PASS: Cloudflare MCP schema snapshot matches canonical 124-operation registry")
        return 0
    if current == registry:
        print("Schema catalog already up to date")
        return 0
    encoded = json.dumps(registry, separators=(",", ":"), ensure_ascii=False)
    updated = text[: match.start()] + "const SCHEMA_CATALOG=" + encoded + ";" + text[match.end() :]
    TARGET.write_text(updated, encoding="utf-8")
    print("Updated full operation schema snapshot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
