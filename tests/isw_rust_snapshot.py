#!/usr/bin/env python3
"""Disposable Rust-backed ISW integration and screenshot evidence.

Never accesses the user's real SQLite data; only a temporary 10-task fixture.
Requires 'playwright==1.56.0' and its managed Chromium in CI.
"""
import json
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"apps"))
from local_bridge import make_server  # noqa: E402

def run_cli(cli,db,*args):
    result=subprocess.run([str(cli),"--database",str(db),*args],
                          capture_output=True,text=True,check=True,timeout=20)
    return result.stdout

def seed(cli,db):
    specs=[
      ("Daily Production Output Reconciliation","Day 8","Production","done"),
      ("Derrick Mechanical Integrity Check","Day 10","Rig & Crew","in_progress"),
      ("Shale Storage Tank Volume Verification","Day 12","Production","done"),
      ("Export Consignment Preparation — 10,000 Barrels","Day 60","Exports","in_progress"),
      ("Loading Window Coordination — Taiwan","Day 60","Exports","todo"),
      ("Environmental Compliance Review","Day 18","Inspection","in_progress"),
      ("Department of Energy Inspection Readiness","Day 20","Inspection","todo"),
      ("Safety Drill and Crew Certification Audit","Day 14","Rig & Crew","in_progress"),
      ("Shareholder Export Approval Packet","Day 28","Exports","todo"),
      ("Final Loading Authorization","Day 59","Exports","todo"),
    ]
    ids=[]
    for title,day,project,status in specs:
        out=run_cli(cli,db,"add",title,"--project",project,"--priority","medium",
                    "--notes",f"Hypothetical offshore export workflow. Target loading in 60 days. {day}.")
        match=re.search(r"\[([0-9a-f-]{36})\]",out,re.I)
        assert match, out
        identifier=match.group(1)
        ids.append(identifier)
        if status!="todo":run_cli(cli,db,"status",identifier,status)
    connections=[
      (0,3),(2,3),(1,6),(7,6),(3,8),(6,8),(5,9),(6,9),(8,9),(9,4)
    ]
    dependencies={t:[] for _,t in connections}
    for start,end in connections:dependencies[end].append(ids[start])
    for target,from_ids in dependencies.items():
        run_cli(cli,db,"depends",ids[target],*[item for dep in from_ids for item in ("--on",dep)])
    return ids

def get(url):
    with urlopen(url,timeout=15) as resp:return json.load(resp)

def post(url,body):
    payload=json.dumps(body).encode("utf-8")
    req=Request(url,data=payload,headers={"Content-Type":"application/json",
            "Origin":url.split("/api/")[0]},method="POST")
    try:
        with urlopen(req,timeout=15) as resp:return resp.status,json.load(resp)
    except HTTPError as exc:return exc.code,json.load(exc)

def main():
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument("--cli",required=True)
    parser.add_argument("--output-dir",default="isw-snapshot")
    args=parser.parse_args()
    cli=Path(args.cli).resolve()
    out=Path(args.output_dir).resolve()
    out.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="shiori-isw-fixture-") as tmp:
        db=Path(tmp)/"demo.sqlite3"
        ids=seed(cli,db)
        server=make_server(0,cli,db)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        base=f"http://127.0.0.1:{server.server_port}"
        try:
            scene=get(base+"/api/isw/scene")
            assert scene["source"]=="rust-sqlite",scene
            assert len(scene["tasks"])==10,len(scene["tasks"])
            assert len(scene["edges"])==10,len(scene["edges"])
            assert scene["positions"]==[],scene["positions"]
            status,position=post(base+"/api/isw/position",{
                "task_id":ids[3],"x":510.0,"y":220.0,"expected_revision":0})
            assert status==200,(status,position)
            assert position["position"]["revision"]==1
            bad_status,_=post(base+"/api/isw/position",{
                "task_id":ids[3],"x":999,"y":999,"expected_revision":0})
            assert bad_status==409,bad_status
            scene=get(base+"/api/isw/scene")
            assert len(scene["positions"])==1
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True)
                errors=[]
                desktop=browser.new_page(viewport={"width":1600,"height":980},device_scale_factor=1)
                desktop.on("pageerror",lambda err:errors.append(str(err)))
                desktop.goto(base+"/isw.html",wait_until="networkidle",timeout=40000)
                desktop.wait_for_function("() => document.getElementById('crumbLabel')?.textContent === 'LIVE RUST / SQLITE'",timeout=20000)
                desktop.wait_for_function("() => window.__iswDebug?.getNodes()?.length === 10",timeout=20000)
                desktop.locator("#fitBottom").click()
                desktop.screenshot(path=str(out/"isw-rust-desktop.png"),full_page=True)
                assert desktop.locator(".node").count()>0,"No visible rust-backed task nodes"
                assert not errors,errors
                mobile=browser.new_page(viewport={"width":430,"height":932},device_scale_factor=1,is_mobile=True,has_touch=True)
                mobile.on("pageerror",lambda err:errors.append(str(err)))
                mobile.goto(base+"/isw.html",wait_until="networkidle",timeout=40000)
                mobile.wait_for_function("() => document.getElementById('crumbLabel')?.textContent === 'LIVE RUST / SQLITE'",timeout=20000)
                mobile.screenshot(path=str(out/"isw-rust-mobile.png"),full_page=True)
                assert not errors,errors
                browser.close()
            (out/"evidence.json").write_text(json.dumps({
                "source":"Rust SQLite temporary fixture","tasks":10,"verified_dependencies":10,
                "position_revisions_tested":True,
                "desktop_png":"isw-rust-desktop.png","mobile_png":"isw-rust-mobile.png",
                "real_user_data":False
            },indent=2))
        finally:
            server.shutdown()
            server.server_close()

if __name__=="__main__":
    main()
