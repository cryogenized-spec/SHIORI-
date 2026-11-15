#!/usr/bin/env python3
"""Compare owner code stored on this device with Cloudflare's Worker secret.

This script never prints, uploads or logs the plaintext code. It sends only
HMAC-SHA256(code, fresh server challenge). Diagnostic endpoint must be
temporarily enabled by the workspace owner; it is removed after debugging.
"""
import hashlib
import hmac
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE="https://shiori-auth.cryogenized.workers.dev"
FILE=Path.home()/".config/shiori/oauth-approval-code"
UA="ShioriOwnerDiagnostic/0.1 (+https://github.com/cryogenized-spec/SHIORI-)"
def request(method,body=None):
    raw=None if body is None else json.dumps(body).encode()
    headers={"User-Agent":UA,"Accept":"application/json"}
    if body is not None:headers["Content-Type"]="application/json"
    req=urllib.request.Request(BASE+"/owner-diagnostic",data=raw,method=method,headers=headers)
    with urllib.request.urlopen(req,timeout=25) as res:
        if res.status!=200:raise RuntimeError("Unexpected Worker response")
        return json.load(res)

def main():
    if not FILE.is_file():
        print("Owner code file not found:",FILE)
        return 1
    secret=FILE.read_bytes().strip()
    if not secret or len(secret)>160:
        print("Invalid local owner-code file length (value withheld)")
        return 1
    challenge=request("GET")
    challenge_hex=challenge.get("challenge","")
    if not isinstance(challenge_hex,str) or len(challenge_hex)!=64:
        raise RuntimeError("Invalid challenge response")
    challenge_raw=challenge_hex.encode()
    try:bytes.fromhex(challenge_hex)
    except ValueError as e:raise RuntimeError("Malformed challenge") from e
    proof=hmac.new(secret,challenge_raw,hashlib.sha256).hexdigest()
    result=request("POST",{"id":challenge["id"],"proof":proof})
    if result.get("matches") is True:
        print("MATCH: local OAuth code equals the code installed in Cloudflare.")
        print("If the browser rejects it, the issue is the value submitted in the form or how it is encoded.")
    elif result.get("matches") is False:
        print("MISMATCH: your local OAuth file does not match the installed Cloudflare secret.")
        print("Do not regenerate either secret. We can investigate the Cloudflare Worker binding safely.")
    else:raise RuntimeError("Unexpected diagnostic response")
    return 0
if __name__=="__main__":
    try:sys.exit(main())
    except (OSError,RuntimeError,KeyError,ValueError,urllib.error.HTTPError) as exc:
        print("Diagnostic could not complete:",type(exc).__name__,file=sys.stderr)
        sys.exit(2)
