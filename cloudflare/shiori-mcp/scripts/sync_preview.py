#!/usr/bin/env python3
"""Read-only local Rust <-> Cloudflare D1 comparison.

NO local or remote task writes, imports, or token logging. S1 compares
local/cloud tombstones and revisions; cursor pages are not atomic snapshots.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import struct
import sys
from urllib.request import Request, urlopen

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"apps"))
from local_bridge import decode_snapshot  # noqa:E402

DEFAULT_BASE="https://shiori-mcp-alpha.cryogenized.workers.dev"
USER_AGENT="ShioriSyncPreview/0.1 (+https://github.com/cryogenized-spec/SHIORI-)"
MAX_TASKS=5000

def load_local(cli: Path, database: Path | None) -> list[dict]:
    args=[str(cli)]
    if database:
        args.extend(["--database",str(database)])
    args.append("bridge-dump")
    result=subprocess.run(args,capture_output=True,timeout=35,check=True)
    return decode_snapshot(result.stdout)


def decode_manifest(data: bytes) -> list[dict]:
    """Parse the local Rust length-prefixed identity manifest.

    This intentionally contains no customer titles, task bodies or notes.
    It cannot be fed to the cloud as a batch import.
    """
    marker = b"SHIORI-MANIFEST-1\n"
    if not isinstance(data, bytes) or not data.startswith(marker):
        raise ValueError("Unexpected local manifest version")
    rows = []
    offset = len(marker)
    while offset < len(data):
        if len(rows) >= MAX_TASKS:
            raise ValueError("Local manifest exceeds task budget")
        fields = []
        for _ in range(6):
            if offset + 4 > len(data):
                raise ValueError("Truncated manifest record")
            size = struct.unpack_from(">I", data, offset)[0]
            offset += 4
            if size > 4096 or offset + size > len(data):
                raise ValueError("Invalid manifest field size")
            fields.append(data[offset:offset + size].decode("utf-8"))
            offset += size
        task_id, version, status, updated, deleted, prerequisites = fields
        if not task_id or not version.isdecimal() or int(version) < 1:
            raise ValueError("Invalid local task identity/version")
        if status not in ("todo", "in_progress", "done"):
            raise ValueError("Invalid task status in manifest")
        deps = prerequisites.split(",") if prerequisites else []
        if len(deps) != len(set(deps)) or task_id in deps:
            raise ValueError("Invalid local prerequisite identities")
        rows.append({
            "id": task_id, "version": int(version), "status": status,
            "updated_at": updated, "deleted": bool(deleted), "depends_on": deps,
        })
    if len({r["id"] for r in rows}) != len(rows):
        raise ValueError("Duplicate task IDs in manifest")
    return rows


def load_local_manifest(cli: Path, database: Path | None) -> list[dict]:
    args = [str(cli)]
    if database:
        args.extend(["--database", str(database)])
    args.append("bridge-manifest")
    output = subprocess.run(args, capture_output=True, timeout=35, check=True)
    return decode_manifest(output.stdout)


def compare_manifest(local: list[dict], remote: list[dict]) -> dict:
    """Compare identity/version/tombstones only. Never infer provenance."""
    # Duplicate identities make counts and conflict classification ambiguous. Fail closed
    # rather than silently overwriting one record in the dictionary projections.
    for source, rows in (("local", local), ("remote", remote)):
        ids = [row["id"] for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate {source} task identities in manifest")
    la={x["id"]:x for x in local if not x["deleted"]}
    ld={x["id"]:x for x in local if x["deleted"]}
    ra={x["id"]:x for x in remote if not x.get("deleted_at")}
    rd={x["id"]:x for x in remote if x.get("deleted_at")}
    overlap=la.keys() & ra.keys()
    return {
        "mode":"s1_read_only_manifest_no_sync",
        "data_boundary":"local Rust SQLite and cloud D1 remain independent",
        "counts":{
            "local_active":len(la),"local_tombstones":len(ld),
            "local_dependency_edges":sum(len(x["depends_on"]) for x in la.values()),
            "remote_active":len(ra),"remote_tombstones":len(rd),
            "matching_active_ids_unverified":len(overlap),
            "matching_id_revision_differences":sum(la[k]["version"]!=ra[k]["version"] for k in overlap),
            "local_active_only":len(la.keys() - (ra.keys() | rd.keys())),
            "remote_active_only":len(ra.keys() - la.keys()),
            "local_deleted_remote_active":len(ld.keys() & ra.keys()),
            "local_active_remote_deleted":len(la.keys() & rd.keys()),
            "matching_deleted_ids_unverified":len(ld.keys() & rd.keys()),
        },
        "warnings":[
            "Same IDs are not verified provenance or permission to merge.",
            "Remote manifest ID pages are not an atomic snapshot.",
            "Active/deleted differences need explicit conflict review.",
            "No local task contents or identifiers were sent to Cloudflare.",
            "Neither local nor remote database was modified.",
        ],
    }


def remote_request(base: str, token: str, cursor: str|None) -> dict:
    data={"workspace_id":"personal","limit":100}
    if cursor:data["cursor"]=cursor
    req=Request(base.rstrip("/")+"/api/v1/ops/tasks.list",
        data=json.dumps(data).encode("utf-8"),method="POST",
        headers={"Content-Type":"application/json","User-Agent":USER_AGENT,
                 "Authorization":"Bearer "+token})
    with urlopen(req,timeout=25) as response:
        payload=json.load(response)
    if not payload.get("ok"):raise ValueError("Cloudflare task read failed")
    result=payload["data"]
    if not isinstance(result.get("items"),list):raise ValueError("Malformed remote task list")
    return result

def load_remote(base:str,token:str) -> list[dict]:
    all_rows=[]
    cursor=None
    seen=set()
    while True:
        response=remote_request(base,token,cursor)
        all_rows.extend(response["items"])
        if len(all_rows)>MAX_TASKS:raise ValueError("Remote result exceeds safe budget")
        next_cursor=response.get("next_cursor")
        if next_cursor is None:return all_rows
        if next_cursor in seen:raise ValueError("Remote pagination loop")
        seen.add(next_cursor)
        cursor=next_cursor

def remote_manifest_request(base: str, token: str, cursor: str | None) -> dict:
    data={"workspace_id":"personal","limit":100}
    if cursor:data["cursor"]=cursor
    req=Request(base.rstrip("/")+"/api/v1/ops/sync.manifest.read",
        data=json.dumps(data).encode("utf-8"),method="POST",
        headers={"Content-Type":"application/json","User-Agent":USER_AGENT,
                 "Authorization":"Bearer "+token})
    with urlopen(req,timeout=25) as response:payload=json.load(response)
    if not payload.get("ok") or payload.get("operation_id")!="sync.manifest.read":
        raise ValueError("Remote manifest request failed")
    result=payload.get("data")
    if not isinstance(result,dict) or result.get("consistent_snapshot") is not False or result.get("local_rust_sync") is not False:
        raise ValueError("Untrusted remote manifest")
    items=result.get("items")
    if not isinstance(items,list) or len(items)>100:raise ValueError("Invalid remote page")
    for row in items:
        if not isinstance(row,dict) or set(row)!={"id","version","status","updated_at","deleted_at"}:
            raise ValueError("Unexpected remote manifest fields")
        if (not isinstance(row["id"],str) or not row["id"] or len(row["id"])>4096 or
            type(row["version"]) is not int or row["version"]<1 or
            row["status"] not in ("todo","in_progress","done") or
            not isinstance(row["updated_at"],str) or len(row["updated_at"])>4096 or
            (row["deleted_at"] is not None and
             (not isinstance(row["deleted_at"],str) or len(row["deleted_at"])>4096))):
            raise ValueError("Malformed manifest task")
    return result


def load_remote_manifest(base:str,token:str)->list[dict]:
    rows=[]
    cursor=None
    seen=set()
    while True:
        page=remote_manifest_request(base,token,cursor)
        for row in page["items"]:
            # The ordering invariant applies within each page as well as across
            # cursor boundaries. Reject duplicates before producing any report.
            if cursor is not None and row["id"]<=cursor:
                raise ValueError("Manifest not strictly ordered")
            cursor=row["id"]
            rows.append(row)
        if len(rows)>MAX_TASKS:raise ValueError("Remote manifest exceeds safe budget")
        nxt=page.get("next_cursor")
        if nxt is None:return rows
        if not isinstance(nxt,str) or nxt!=cursor or nxt in seen:
            raise ValueError("Invalid manifest cursor")
        seen.add(nxt)

def normalize(title:str)->str:
    return " ".join(title.casefold().split())

def fingerprint(row:dict)->str:
    title=normalize(row.get("title",""))
    project=normalize(row.get("project",""))
    return hashlib.sha256((title+"\x00"+project).encode("utf-8")).hexdigest()[:16]

def compare(local:list[dict],remote:list[dict])->dict:
    """Do not infer task identity from titles: classify as potential only."""
    # The legacy full-record preview must not hide repeated identities either.
    # Never include task identifiers in errors or output.
    for source, rows in (("local", local), ("remote", remote)):
        ids = [row["id"] for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError(f"Duplicate {source} task identities in preview")
    local_by={x["id"]:x for x in local}
    remote_by={x["id"]:x for x in remote}
    common=set(local_by)&set(remote_by)
    changed=[
      x for x in common
      if any(local_by[x].get(k)!=remote_by[x].get(k) for k in ("title","status","project"))
    ]
    left=[x for x in local if x["id"] not in common]
    right=[x for x in remote if x["id"] not in common]
    a,b={},{}
    for x in left:a.setdefault(fingerprint(x),[]).append(x["id"])
    for x in right:b.setdefault(fingerprint(x),[]).append(x["id"])
    maybes=sum(min(len(a[key]),len(b[key])) for key in a.keys()&b.keys())
    return {
       "mode":"read_only_no_writes",
       "data_boundary":"remote Cloudflare D1 remains separate from Rust SQLite",
       "counts":{
         "local_total":len(local),"remote_total":len(remote),
         "same_id":len(common),"same_id_changed":len(changed),
         "local_only":len(left),"remote_only":len(right),
         "possible_title_matches_not_authoritative":maybes
       },
       "warnings":[
          "Matching names do not prove shared identity or safe merge.",
          "No local data was uploaded to Cloudflare.",
          "No remote records were changed.",
          "Revisions, provenance, deletes and offline conflict replay require a dedicated sync protocol."
       ]
    }

def read_secret(args):
    value=os.environ.get("SHIORI_MCP_TOKEN")
    if not value and args.token_file:
        value=Path(args.token_file).expanduser().read_text(encoding="utf-8").strip()
    if not value:raise ValueError("Use SHIORI_MCP_TOKEN or --token-file")
    return value

def main():
    p=argparse.ArgumentParser(description="Compare Rust and Cloudflare tasks without changes")
    p.add_argument("--cli",default="target/debug/shiori-cli")
    p.add_argument("--database",type=Path)
    p.add_argument("--base",default=DEFAULT_BASE)
    p.add_argument("--token-file",type=Path)
    p.add_argument("--manifest",action="store_true",help="Compare local Rust task IDs, revisions and tombstone counts without exposing content")
    p.add_argument("--report-file",type=Path,help="Write counts-only JSON report to the specified local file")
    args=p.parse_args()
    token=read_secret(args)
    local=load_local_manifest(Path(args.cli),args.database) if args.manifest else load_local(Path(args.cli),args.database)
    if len(local)>MAX_TASKS:raise ValueError("Local result exceeds safe budget")
    remote=load_remote_manifest(args.base,token) if args.manifest else load_remote(args.base,token)
    report=compare_manifest(local,remote) if args.manifest else compare(local,remote)
    print(json.dumps(report,indent=2))
    if args.report_file:
        args.report_file.parent.mkdir(parents=True,exist_ok=True)
        args.report_file.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    return 0

if __name__=="__main__":
    try:sys.exit(main())
    except (ValueError,OSError,subprocess.CalledProcessError) as exc:
        print("Sync preview failed:",type(exc).__name__,str(exc),file=sys.stderr)
        sys.exit(1)