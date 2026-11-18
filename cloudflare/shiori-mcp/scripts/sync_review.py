#!/usr/bin/env python3
"""Offline, counts-only comparison of SHIORI's local manifest with an S3 D1 baseline.

Never opens the canonical task DB, connects to Cloudflare, or mutates the pull journal.
An identical task ID is NOT evidence that task origins have been verified.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
import sys
from urllib.parse import quote

MARKER = b"SHIORI-MANIFEST-1\n"
MAX_LOCAL_BYTES = 4_000_000
MAX_LOCAL_ITEMS = 10_000
ID = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
STATUSES = {"todo", "in_progress", "done"}


class ReviewError(ValueError):
    pass


def private_file_bytes(path: Path, limit: int, *, metadata_only: bool = False) -> bytes:
    """Read a regular 0600 file, refusing symlinks, with a hard read budget."""
    fd = os.open(path.expanduser(), os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise ReviewError("Input must be a private regular file (0600)")
        if metadata_only:
            return b""
        if info.st_size > limit:
            raise ReviewError("Input exceeds bounded metadata budget")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        if len(data) > limit:
            raise ReviewError("Input exceeds bounded metadata budget")
        return data
    finally:
        os.close(fd)


def local_manifest(data: bytes) -> tuple[dict, set]:
    if not data.startswith(MARKER):
        raise ReviewError("Expected binary SHIORI-MANIFEST-1 export, not task dump")
    pos = len(MARKER)
    rows = {}
    edges = set()
    prev = ""
    while pos < len(data):
        if len(rows) >= MAX_LOCAL_ITEMS:
            raise ReviewError("Too many local task identities")
        fields = []
        for _ in range(6):
            if pos + 4 > len(data):
                raise ReviewError("Truncated local manifest length")
            length = struct.unpack_from(">I", data, pos)[0]
            pos += 4
            if length > 4096 or pos + length > len(data):
                raise ReviewError("Truncated or oversized local manifest field")
            try:
                fields.append(data[pos:pos + length].decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise ReviewError("Manifest contains invalid UTF-8") from exc
            pos += length
        task_id, version, status, updated, deleted, depends = fields
        if not ID.fullmatch(task_id) or task_id <= prev:
            raise ReviewError("Unordered, repeated or invalid local task ID")
        prev = task_id
        if not version.isdecimal() or not 1 <= int(version) <= 2**53 - 1:
            raise ReviewError("Invalid local revision")
        if status not in STATUSES or not 0 < len(updated) <= 60 or len(deleted) > 60:
            raise ReviewError("Invalid local task metadata")
        links = [] if not depends else depends.split(",")
        if deleted and links:
            raise ReviewError("Deleted local task has active dependencies")
        if len(set(links)) != len(links) or any(not ID.fullmatch(x) or x == task_id for x in links):
            raise ReviewError("Invalid local dependency identities")
        rows[task_id] = (int(version), status, deleted or None)
        edges.update((task_id, x) for x in links)
    return rows, edges


def baseline_journal(path: Path) -> tuple[dict, set, int, int, int, bool]:
    # Verify that the existing file is not a symlink or world-readable.
    private_file_bytes(path, 0, metadata_only=True)
    file_path = path.expanduser().resolve()
    uri = "file:" + quote(str(file_path), safe="/") + "?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        con.execute("PRAGMA query_only=ON")
        con.execute("BEGIN")  # One read snapshot across checkpoint, inventory, and feed counts.
        if con.execute("PRAGMA user_version").fetchone()[0] != 2:
            raise ReviewError("Only staged v2 pull journals are supported")
        state = con.execute("SELECT cursor,cutoff,baseline_required FROM pull_state WHERE workspace_id='personal'").fetchone()
        meta = con.execute("SELECT cutoff,task_count,edge_count,sha256 FROM pull_baseline_meta WHERE workspace_id='personal'").fetchone()
        if not state or not meta or state[2] != 1 or state[0] < meta[0]:
            raise ReviewError("Baseline is missing or pull checkpoint is untrusted")
        cutoff, task_count, edge_count, digest = meta
        rows = con.execute("SELECT id,version,status,updated_at,deleted_at FROM pull_baseline_tasks ORDER BY id").fetchall()
        edges = con.execute("SELECT task_id,depends_on_id FROM pull_baseline_edges ORDER BY task_id,depends_on_id").fetchall()
        if len(rows) != task_count or len(edges) != edge_count or task_count > 100 or edge_count > 200:
            raise ReviewError("Remote baseline counts are inconsistent")
        snapshot = {
            "items": [dict(zip(("id", "version", "status", "updated_at", "deleted_at"), row)) for row in rows],
            "edges": [dict(zip(("task_id", "depends_on_id"), edge)) for edge in edges],
            "cutoff": cutoff, "task_count": task_count, "edge_count": edge_count,
            "consistent_snapshot": True, "local_rust_sync": False, "automatic_apply": False,
        }
        actual = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if actual != digest:
            raise ReviewError("Staged baseline digest mismatch")
        ids = {r[0] for r in rows}
        if len(ids) != len(rows) or any(a not in ids or b not in ids or a == b for a, b in edges):
            raise ReviewError("Staged baseline contains invalid dependencies")
        delta = con.execute("SELECT COUNT(*) FROM pull_events WHERE seq > ?", (cutoff,)).fetchone()[0]
        prior = con.execute("SELECT COUNT(*) FROM pull_events WHERE seq <= ?", (cutoff,)).fetchone()[0]
        if prior:
            raise ReviewError("Pull journal contains pre-baseline events; cannot review safely")
        remote = {task_id: (version, status, deleted_at) for task_id, version, status, _, deleted_at in rows}
        return remote, set(edges), cutoff, state[0], delta, state[1] is not None
    except sqlite3.Error as exc:
        raise ReviewError("Invalid or unreadable pull journal schema") from exc
    finally:
        con.close()


def compare(local: dict, local_edges: set, remote: dict, remote_edges: set,
            cutoff: int, checkpoint: int, delta: int, incomplete_page: bool) -> dict:
    li, ri = set(local), set(remote)
    both = li & ri
    return {
        "remote_baseline_cutoff": cutoff,
        "remote_journal_checkpoint": checkpoint,
        "post_baseline_remote_events": delta,
        "unfinished_remote_event_page": incomplete_page,
        "local_tasks": len(local),
        "remote_baseline_tasks": len(remote),
        "local_only_ids": len(li - ri),
        "remote_only_baseline_ids": len(ri - li),
        "shared_ids_provenance_unverified": len(both),
        "shared_ids_revision_disagreement": sum(local[k][0] != remote[k][0] for k in both),
        "delete_vs_active_disagreement": sum(bool(local[k][2]) != bool(remote[k][2]) for k in both),
        "local_dependency_edges": len(local_edges),
        "remote_baseline_dependency_edges": len(remote_edges),
        "local_only_dependency_edges": len(local_edges - remote_edges),
        "remote_only_baseline_dependency_edges": len(remote_edges - local_edges),
        "unresolved_local_dependency_edges": sum(a not in li or b not in li for a, b in local_edges),
        "baseline_is_not_current_remote_when_deltas_exist": bool(delta or incomplete_page),
        "identity_review_required": True,
        "safe_to_apply": False,
        "data_transfer_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline identity-count review; no task writes or Cloudflare requests")
    parser.add_argument("--journal", type=Path, required=True, help="Existing private S3 v2 pull journal")
    parser.add_argument("--local-manifest", type=Path, required=True,
                        help="Private binary export from shiori-cli bridge-manifest")
    args = parser.parse_args()
    try:
        local, local_edges = local_manifest(private_file_bytes(args.local_manifest, MAX_LOCAL_BYTES))
        remote, remote_edges, cutoff, checkpoint, delta, incomplete = baseline_journal(args.journal)
        print(json.dumps(compare(local, local_edges, remote, remote_edges, cutoff, checkpoint,
                                 delta, incomplete), indent=2, sort_keys=True))
        return 0
    except (ReviewError, OSError) as exc:
        print("SHIORI offline sync review: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
