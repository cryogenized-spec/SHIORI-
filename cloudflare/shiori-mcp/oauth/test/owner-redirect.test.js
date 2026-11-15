import test from "node:test";
import assert from "node:assert/strict";
import {ownerRedirect} from "../owner-redirect.js";

test("documents original immutable redirect header failure",()=>{
  const original=Response.redirect("https://client.example/cb?code=test",302);
  assert.throws(()=>original.headers.set("set-cookie","token=none"),/immutable/i);
});
test("creates 302 callback with already attached host-only cookie removal",()=>{
  const url="https://client.example/cb?state=abc&code=test";
  const result=ownerRedirect(url);
  assert.equal(result.status,302);
  assert.equal(result.headers.get("location"),url);
  assert.match(result.headers.get("set-cookie"),/^__Host-shiori_oauth=;/);
  assert.match(result.headers.get("set-cookie"),/Max-Age=0/);
  assert.match(result.headers.get("set-cookie"),/HttpOnly/);
  assert.match(result.headers.get("set-cookie"),/Secure/);
  assert.equal(result.headers.get("cache-control"),"no-store");
});
test("does not include approval code or OAuth bearer token in any response header",()=>{
  const result=ownerRedirect("https://client.example/callback?state=test");
  assert.equal(result.headers.has("authorization"),false);
  assert.equal(result.headers.has("x-owner-code"),false);
});
test("invalid redirects fail before consuming pending consent",()=>{
  assert.throws(()=>ownerRedirect("not a URL"),TypeError);
  assert.throws(()=>ownerRedirect(""),TypeError);
});
