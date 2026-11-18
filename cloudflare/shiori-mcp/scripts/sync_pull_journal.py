#!/usr/bin/env python3
"""Content-free S3 D1 change-feed receiver, with a private durable local cursor.

Never writes tasks.sqlite3, never applies a change to Rust task contents,
and never treats an event as proof that an initial snapshot was reconciled.
Use only an owner-controlled legacy bearer token file, NOT the OAuth code.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REMOTE_URL = "https://shiori-mcp-alpha.cryogenized.workers.dev/api/v1/ops/sync.changes.read"
BASELINE_URL = "https://shiori-mcp-alpha.cryogenized.workers.dev/api/v1/ops/sync.baseline.read"
WORKSPACE = "personal"
KNOWN_KINDS = {"task.insert", "task.update", "task.delete", "task.purge",
               "edge.add", "edge.remove"}
ROW_FIELDS = {"seq", "kind", "task_id", "depends_on_id", "task_version", "occurred_at"}
PAGE_FIELDS = {"changes", "cutoff", "checkpoint_cursor", "next_cursor",
               "baseline_required", "local_rust_sync"}
MAX_ROWS = 50_000
PAGE_LIMIT = 100
SCHEMA = 2


class PullError(ValueError):
    pass


def check_private(path: Path) -> Path:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise PullError("File must be private (0600), regular and not a symlink: " + str(path))
    return path


def init_journal(path: Path) -> sqlite3.Connection:
    path = path.expanduser()
    try:
        check_private(path)
    except FileNotFoundError:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        os.close(descriptor)
        check_private(path)
    con = sqlite3.connect(str(path), timeout=5)
    try:
        con.execute("PRAGMA busy_timeout=4000")
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, SCHEMA):
            raise PullError(f"Unsupported pull journal version {version}; no migration attempted")
        if version == 0:
            tables = con.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%'"
            ).fetchone()[0]
            if tables:
                raise PullError("Refusing to convert an existing database into a pull journal")
            with con:
                con.executescript("""
                    CREATE TABLE pull_state (
                      workspace_id TEXT PRIMARY KEY,
                      cursor INTEGER NOT NULL DEFAULT 0 CHECK(cursor >= 0),
                      cutoff INTEGER CHECK(cutoff IS NULL OR cutoff >= 0),
                      baseline_required INTEGER NOT NULL DEFAULT 1 CHECK(baseline_required = 1)
                    );
                    CREATE TABLE pull_events (
                      seq INTEGER PRIMARY KEY CHECK(seq > 0),
                      kind TEXT NOT NULL,
                      task_id TEXT NOT NULL,
                      depends_on_id TEXT,
                      task_version INTEGER,
                      occurred_at TEXT NOT NULL
                    );
                    INSERT INTO pull_state(workspace_id,cursor,cutoff,baseline_required)
                      VALUES('personal',0,NULL,1);
                    PRAGMA user_version=1;
                """)

        # v1 -> v2 is additive: preserve all events, checkpoints and the
        # required-review flag while adding a *metadata-only* baseline.
        if version in (0,1):
            with con:
                con.execute("""CREATE TABLE pull_baseline_meta (
                    workspace_id TEXT PRIMARY KEY,
                    cutoff INTEGER NOT NULL CHECK(cutoff>=0),
                    task_count INTEGER NOT NULL CHECK(task_count>=0),
                    edge_count INTEGER NOT NULL CHECK(edge_count>=0),
                    sha256 TEXT NOT NULL CHECK(length(sha256)=64)
                )""")
                con.execute("""CREATE TABLE pull_baseline_tasks (
                    id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL CHECK(version>=1),
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                )""")
                con.execute("""CREATE TABLE pull_baseline_edges (
                    task_id TEXT NOT NULL,
                    depends_on_id TEXT NOT NULL,
                    PRIMARY KEY(task_id,depends_on_id)
                )""")
                con.execute("PRAGMA user_version=2")
        row = con.execute("SELECT cursor,cutoff,baseline_required FROM pull_state "
                          "WHERE workspace_id=?", (WORKSPACE,)).fetchone()
        if not row or row[2] != 1:
            raise PullError("Untrusted pull journal state; refusing to discard baseline requirement")
        return con
    except Exception:
        con.close()
        raise


def token_from_file(path: Path) -> str:
    token = check_private(path.expanduser()).read_text(encoding="utf-8").strip()
    if not token or len(token) > 240:
        raise PullError("Invalid token file; use private legacy owner bearer token, not approval code")
    return token


def state(con: sqlite3.Connection) -> tuple[int, int | None, bool, int]:
    row = con.execute("SELECT cursor,cutoff,baseline_required FROM pull_state WHERE workspace_id=?",
                      (WORKSPACE,)).fetchone()
    if not row:
        raise PullError("Missing pull checkpoint")
    count = con.execute("SELECT COUNT(*) FROM pull_events").fetchone()[0]
    return row[0], row[1], bool(row[2]), count


def request_page(token: str, cursor: int, cutoff: int | None) -> dict:
    args = {"workspace_id": WORKSPACE, "cursor": cursor, "limit": PAGE_LIMIT}
    if cutoff is not None:
        args["cutoff"] = cutoff
    request = Request(
        REMOTE_URL, method="POST",
        data=json.dumps(args, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                 "User-Agent": "ShioriReadOnlyPullJournal/0.1"},
    )
    try:
        with urlopen(request, timeout=25) as response:
            raw = response.read(200001)
            if len(raw) > 200000:
                raise PullError("Remote change-feed page exceeds safe response size")
            reply = json.loads(raw)
    except HTTPError as exc:
        raise PullError(f"Owner-authenticated remote change feed rejected request (HTTP {exc.code})") from None
    except (URLError, TimeoutError) as exc:
        raise PullError("Remote change feed unreachable; persisted cursor has not advanced") from exc
    if (not isinstance(reply, dict) or reply.get("ok") is not True
            or reply.get("operation_id") != "sync.changes.read"):
        raise PullError("Invalid remote operation envelope")
    return reply.get("data")



BASELINE_FIELDS={"items","edges","cutoff","task_count","edge_count",
                 "consistent_snapshot","local_rust_sync","automatic_apply"}
BASELINE_TASK_FIELDS={"id","version","status","updated_at","deleted_at"}
BASELINE_EDGE_FIELDS={"task_id","depends_on_id"}


def request_baseline(token: str) -> dict:
    """Only a content-free read is allowed, even during first-time setup."""
    req = Request(
        BASELINE_URL, method="POST",
        data=json.dumps({"workspace_id":WORKSPACE},separators=(",",":")).encode(),
        headers={"Content-Type":"application/json","Authorization":"Bearer "+token,
                 "User-Agent":"ShioriReadOnlyBaseline/0.1"},
    )
    try:
        with urlopen(req,timeout=25) as response:
            raw=response.read(200001)
            if len(raw)>200000:
                raise PullError("Remote baseline response exceeds safe budget")
            reply=json.loads(raw)
    except HTTPError as exc:
        raise PullError(f"Remote baseline rejected read (HTTP {exc.code})") from None
    except (URLError,TimeoutError) as exc:
        raise PullError("Remote baseline unavailable; no local checkpoint changed") from exc
    if (not isinstance(reply,dict) or reply.get("ok") is not True
            or reply.get("operation_id")!="sync.baseline.read"):
        raise PullError("Unexpected baseline response wrapper")
    return reply.get("data")


def check_baseline(snapshot: object) -> tuple[dict,str]:
    """Validate every field before committing a remote-supplied checkpoint."""
    import re
    if not isinstance(snapshot,dict) or set(snapshot)!=BASELINE_FIELDS:
        raise PullError("Unknown baseline fields (possibly private task content)")
    if (snapshot["consistent_snapshot"] is not True
            or snapshot["local_rust_sync"] is not False
            or snapshot["automatic_apply"] is not False):
        raise PullError("Baseline claims unsupported source or application guarantees")
    if not valid_int(snapshot["cutoff"]):
        raise PullError("Invalid high-water sequence")
    tasks=snapshot["items"]
    edges=snapshot["edges"]
    if (not isinstance(tasks,list) or not isinstance(edges,list)
            or len(tasks)>100 or len(edges)>200
            or not valid_int(snapshot["task_count"])
            or not valid_int(snapshot["edge_count"])
            or len(tasks)!=snapshot["task_count"]
            or len(edges)!=snapshot["edge_count"]):
        raise PullError("Incomplete or oversized baseline")
    identifier=re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")
    last=""
    ids=set()
    for task in tasks:
        if not isinstance(task,dict) or set(task)!=BASELINE_TASK_FIELDS:
            raise PullError("Unexpected baseline task fields")
        name=task["id"]
        if (not isinstance(name,str) or not identifier.fullmatch(name)
                or name<=last or not valid_int(task["version"],1)
                or task["status"] not in ("todo","in_progress","done")
                or not isinstance(task["updated_at"],str)
                or not 0<len(task["updated_at"])<=60
                or (task["deleted_at"] is not None and
                    (not isinstance(task["deleted_at"],str)
                     or not 0<len(task["deleted_at"])<=60))):
            raise PullError("Unordered, malformed or duplicate baseline task")
        last=name
        ids.add(name)
    previous_edge=("", "")
    for edge in edges:
        if not isinstance(edge,dict) or set(edge)!=BASELINE_EDGE_FIELDS:
            raise PullError("Unexpected baseline edge fields")
        a=edge["task_id"]
        b=edge["depends_on_id"]
        if (not isinstance(a,str) or not isinstance(b,str)
                or a not in ids or b not in ids or a==b or
                (a,b)<=previous_edge):
            raise PullError("Dangling, malformed or duplicate baseline edge")
        previous_edge=(a,b)
    canonical=json.dumps(snapshot,sort_keys=True,separators=(",",":")).encode()
    return snapshot,hashlib.sha256(canonical).hexdigest()


def persist_baseline(con: sqlite3.Connection, snapshot: dict) -> int:
    snapshot,digest=check_baseline(snapshot)
    cutoff=snapshot["cutoff"]
    with con:
        current=con.execute(
            "SELECT cursor,cutoff,baseline_required FROM pull_state WHERE workspace_id=?",
            (WORKSPACE,)
        ).fetchone()
        prior=con.execute("SELECT COUNT(*) FROM pull_events").fetchone()[0]
        saved=con.execute("SELECT COUNT(*) FROM pull_baseline_meta").fetchone()[0]
        if current!=(0,None,1) or prior or saved:
            raise PullError("Initial baseline requires a fresh, empty pull journal; never overwrite a checkpoint")
        con.execute(
            "INSERT INTO pull_baseline_meta VALUES(?,?,?,?,?)",
            (WORKSPACE,cutoff,snapshot["task_count"],snapshot["edge_count"],digest)
        )
        con.executemany(
            "INSERT INTO pull_baseline_tasks VALUES(?,?,?,?,?)",
            [(t["id"],t["version"],t["status"],t["updated_at"],t["deleted_at"])
             for t in snapshot["items"]]
        )
        con.executemany(
            "INSERT INTO pull_baseline_edges VALUES(?,?)",
            [(e["task_id"],e["depends_on_id"]) for e in snapshot["edges"]]
        )
        updated=con.execute(
            "UPDATE pull_state SET cursor=? WHERE workspace_id=? AND cursor=0 AND cutoff IS NULL AND baseline_required=1",
            (cutoff,WORKSPACE)
        ).rowcount
        if updated!=1:
            raise PullError("Pull journal checkpoint changed concurrently")
    return cutoff


def baseline_info(con: sqlite3.Connection) -> tuple[int,int,int] | None:
    return con.execute(
        "SELECT cutoff,task_count,edge_count FROM pull_baseline_meta WHERE workspace_id=?",
        (WORKSPACE,)
    ).fetchone()


def valid_int(value: object, minimum: int = 0) -> bool:
    return type(value) is int and minimum <= value <= 2**53 - 1


def check_page(page: object, cursor: int, fixed_cutoff: int | None) -> tuple[list[dict], int, int, int | None]:
    if not isinstance(page, dict) or set(page) != PAGE_FIELDS:
        raise PullError("Unexpected change-feed envelope fields")
    if page["baseline_required"] is not True or page["local_rust_sync"] is not False:
        raise PullError("Remote feed claims unsupported snapshot or synchronization guarantees")
    cutoff = page["cutoff"]
    if not valid_int(cutoff) or cutoff < cursor or (fixed_cutoff is not None and cutoff != fixed_cutoff):
        raise PullError("Missing, regressing or changed high-water cutoff")
    events = page["changes"]
    if not isinstance(events, list) or len(events) > PAGE_LIMIT:
        raise PullError("Unbounded event page")
    previous = cursor
    for event in events:
        if not isinstance(event, dict) or set(event) != ROW_FIELDS:
            raise PullError("Unexpected event data (possibly task contents)")
        seq = event["seq"]
        if not valid_int(seq, 1) or not (previous < seq <= cutoff):
            raise PullError("Event sequence is not increasing within the cutoff")
        if (not isinstance(event["kind"], str) or event["kind"] not in KNOWN_KINDS
                or not isinstance(event["task_id"], str) or not 0 < len(event["task_id"]) <= 160
                or not isinstance(event["occurred_at"], str) or not event["occurred_at"]):
            raise PullError("Invalid event identity, kind or timestamp")
        if event["kind"].startswith("task."):
            if event["depends_on_id"] is not None or not valid_int(event["task_version"], 1):
                raise PullError("Task change lacks version or has spurious edge identity")
        elif (not isinstance(event["depends_on_id"], str)
              or not event["depends_on_id"]
              or event["task_version"] is not None):
            raise PullError("Invalid dependency change event")
        previous = seq
    next_cursor = page["next_cursor"]
    checkpoint = page["checkpoint_cursor"]
    if not valid_int(checkpoint) or checkpoint > cutoff:
        raise PullError("Invalid durable checkpoint")
    if next_cursor is None:
        if checkpoint != cutoff:
            raise PullError("Final page failed to checkpoint the full cutoff")
    elif (not valid_int(next_cursor, 1) or not events
          or next_cursor != previous or checkpoint != previous or previous >= cutoff):
        raise PullError("Invalid continuation cursor; no checkpoint committed")
    return events, cutoff, checkpoint, next_cursor


def persist_page(con: sqlite3.Connection, events: list[dict], old_cursor: int,
                 old_cutoff: int | None, cutoff: int, checkpoint: int,
                 next_cursor: int | None) -> None:
    with con:
        current = con.execute(
            "SELECT cursor,cutoff,baseline_required FROM pull_state WHERE workspace_id=?",
            (WORKSPACE,),
        ).fetchone()
        if current != (old_cursor, old_cutoff, 1):
            raise PullError("Another receiver changed this journal; refusing to advance")
        total = con.execute("SELECT COUNT(*) FROM pull_events").fetchone()[0]
        if total + len(events) > MAX_ROWS:
            raise PullError("Local event budget exhausted; do not silently drop history")
        for item in events:
            con.execute(
                "INSERT INTO pull_events(seq,kind,task_id,depends_on_id,task_version,occurred_at)"
                " VALUES(?,?,?,?,?,?)",
                (item["seq"], item["kind"], item["task_id"],
                 item["depends_on_id"], item["task_version"], item["occurred_at"]),
            )
        updated = con.execute(
            "UPDATE pull_state SET cursor=?,cutoff=? "
            "WHERE workspace_id=? AND cursor=? AND "
            "((cutoff IS NULL AND ? IS NULL) OR cutoff=?) AND baseline_required=1",
            (checkpoint, cutoff if next_cursor is not None else None,
             WORKSPACE, old_cursor, old_cutoff, old_cutoff),
        ).rowcount
        if updated != 1:
            raise PullError("Lost concurrent checkpoint update")


def poll(con: sqlite3.Connection, token: str, max_pages: int) -> tuple[int, int, int | None]:
    if not (1 <= max_pages <= 20):
        raise PullError("--max-pages must be 1–20")
    processed = 0
    for _ in range(max_pages):
        cursor, previous_cutoff, baseline, count = state(con)
        if not baseline:
            raise PullError("Baseline flag unexpectedly cleared; journal is not trusted")
        page = request_page(token, cursor, previous_cutoff)
        events, cutoff, checkpoint, more = check_page(page, cursor, previous_cutoff)
        persist_page(con, events, cursor, previous_cutoff, cutoff, checkpoint, more)
        processed += len(events)
        if more is None:
            break
    cursor, cutoff, _baseline, _count = state(con)
    return processed, cursor, cutoff


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only remote change-feed inbox; NEVER applies tasks")
    parser.add_argument("--journal", type=Path,
                        default=Path.home()/".local/share/shiori/tasks.pull.sqlite3")
    parser.add_argument("--token-file", type=Path,
                        help="Private owner bearer file, never the OAuth approval code")
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("action", choices=["status", "baseline", "poll"])
    args = parser.parse_args()
    try:
        journal = init_journal(args.journal)
        try:
            if args.action == "status":
                cursor, cutoff, _baseline, total = state(journal)
                saved = baseline_info(journal)
                note = (f"atomic baseline staged at {saved[0]} ({saved[1]} tasks, {saved[2]} edges)"
                        if saved is not None else "atomic baseline not yet staged")
                print(f"Shiori remote pull inbox: {total} metadata events, checkpoint {cursor}, "
                      f"active cutoff {cutoff}, {note}; identity review still REQUIRED. "
                      "No local task records have been modified.")
                return 0
            if args.token_file is None:
                raise PullError("--token-file is required for baseline or poll")
            token = token_from_file(args.token_file)
            if args.action == "baseline":
                snapshot = request_baseline(token)
                cutoff = persist_baseline(journal, snapshot)
                print(f"Staged a content-free baseline of {snapshot['task_count']} tasks and "
                      f"{snapshot['edge_count']} edges at event cutoff {cutoff}. "
                      "Identity review remains required. No canonical tasks changed.")
                return 0
            count, cursor, cutoff = poll(journal, token, args.max_pages)
            print(f"Stored {count} new change metadata events, durable checkpoint {cursor}, "
                  f"active cutoff {cutoff}. Baseline still REQUIRED. "
                  "No task contents downloaded or applied.")
            return 0
        finally:
            journal.close()
    except (PullError, sqlite3.Error, OSError, ValueError, json.JSONDecodeError) as exc:
        print("Shiori read-only pull journal:", str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
