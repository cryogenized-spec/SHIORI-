#!/usr/bin/env python3
"""Read-only local Rust <-> Cloudflare D1 comparison.

NO local or remote task writes, imports, or token logging. OAuth pairing,
bidirectional sync, conflict resolution and tombstones are separate work.
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
    """Compare identity/version only; titles are never trusted as shared IDs."""
    active = {task["id"]: task for task in local if not task["deleted"]}
    tombstones = {task["id"] for task in local if task["deleted"]}
    remote_by_id = {task["id"]: task for task in remote}
    overlap = active.keys() & remote_by_id.keys()
    return {
        "mode": "s1_read_only_manifest_no_sync",
        "data_boundary": "local Rust SQLite is authoritative locally; cloud D1 remains isolated",
        "counts": {
            "local_active": len(active),
            "local_tombstones": len(tombstones),
            "local_dependency_edges": sum(len(task["depends_on"]) for task in local if not task["deleted"]),
            "remote_active": len(remote),
            "matching_active_ids_unverified": len(overlap),
            "matching_id_revision_differences": sum(
                active[key]["version"] != remote_by_id[key].get("version") for key in overlap
            ),
            "local_active_only": len(active.keys() - remote_by_id.keys()),
            "remote_active_only": len(remote_by_id.keys() - active.keys()),
        },
        "warnings": [
            "Matching identifiers do not prove shared origin without a provenance mapping.",
            "Remote tombstones and edge versions are not exposed by the cloud alpha task list.",
            "No local task content or manifest IDs were transmitted to the cloud.",
            "No local or remote record was changed.",
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

def normalize(title:str)->str:
    return " ".join(title.casefold().split())

def fingerprint(row:dict)->str:
    title=normalize(row.get("title",""))
    project=normalize(row.get("project",""))
    return hashlib.sha256((title+"\x00"+project).encode("utf-8")).hexdigest()[:16]

def compare(local:list[dict],remote:list[dict])->dict:
    """Do not infer task identity from titles: classify as potential only."""
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
    remote=load_remote(args.base,token)
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