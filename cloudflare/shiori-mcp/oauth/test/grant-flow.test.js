import test from "node:test";
import assert from "node:assert/strict";
import {completeOwnerGrant,GrantStageError} from "../grant-flow.js";
const url="https://shiori-auth.cryogenized.workers.dev/authorize?client_id=demo&response_type=code&scope=mcp%3Aread";
function apiWith(overrides={}) {
  return {
    parseAuthRequest:async ()=>({clientId:"demo",scope:["mcp:read","mcp:write"]}),
    lookupClient:async ()=>({clientName:"Test client"}),
    completeAuthorization:async ()=>({redirectTo:"https://example.com/callback?code=test"}),
    ...overrides
  };
}
test("success returns provider redirect, correct user and only permitted scopes",async()=>{
  let received;
  const api=apiWith({completeAuthorization:async args=>{
    received=args;
    return {redirectTo:"https://example.com/callback?code=test"};
  }});
  const r=await completeOwnerGrant(api,url,["mcp:read"]);
  assert.equal(r.redirectTo,"https://example.com/callback?code=test");
  assert.equal(received.userId,"shiori-owner");
  assert.deepEqual(received.scope,["mcp:read"]);
  assert.equal(received.props.userId,"shiori-owner");
});
test("async parse failure is tagged, not an unhandled rejection",async()=>{
  await assert.rejects(completeOwnerGrant(apiWith({
    parseAuthRequest:async()=>{throw new TypeError("invalid parsed request");}
  }),url,["mcp:read"]),e=>e instanceof GrantStageError && e.stage==="restore_request" && e.underlyingType==="TypeError");
});
test("lookup errors are tagged, without leaking original URLs",async()=>{
  await assert.rejects(completeOwnerGrant(apiWith({
    lookupClient:async()=>{throw new Error("sensitive OAuth URL "+url);}
  }),url,["mcp:read"]),e=>e instanceof GrantStageError && e.stage==="lookup_client" && !String(e).includes(url));
});
test("missing client is tagged",async()=>{
  await assert.rejects(completeOwnerGrant(apiWith({
    lookupClient:async()=>null
  }),url,["mcp:read"]),e=>e instanceof GrantStageError && e.stage==="lookup_client");
});
test("grant storage failures are tagged",async()=>{
  await assert.rejects(completeOwnerGrant(apiWith({
    completeAuthorization:async()=>{throw new Error("KV failed");}
  }),url,["mcp:read"]),e=>e instanceof GrantStageError && e.stage==="create_grant");
});
test("invalid grant redirect is tagged",async()=>{
  await assert.rejects(completeOwnerGrant(apiWith({
    completeAuthorization:async()=>({redirectTo:"not a valid url"})
  }),url,["mcp:read"]),e=>e instanceof GrantStageError && e.stage==="validate_redirect");
});

test("owner grant includes write only when requested and approved",async()=>{
 let received;
 const api=apiWith({completeAuthorization:async args=>{
  received=args;
  return {redirectTo:"https://example.com/callback?code=approved"};
 }});
 await completeOwnerGrant(api,url,["mcp:read","mcp:write"],true);
 assert.deepEqual(received.scope,["mcp:read","mcp:write"]);
 // The provider is supplied only the intersection of request and supported
 // scopes. Actual consent is checked before completeOwnerGrant is called.
});

test("read-only ChatGPT request gains write only after explicit owner opt-in",async()=>{
 let scopes;
 const api=apiWith({
   parseAuthRequest:async()=>({clientId:"demo",scope:["mcp:read"]}),
   completeAuthorization:async options=>{scopes=options.scope;return {redirectTo:"https://example.com/callback?code=ok"};}
 });
 await completeOwnerGrant(api,url,["mcp:read","mcp:write"]);
 assert.deepEqual(scopes,["mcp:read"],"default must be read-only");
 await completeOwnerGrant(api,url,["mcp:read","mcp:write"],true);
 assert.deepEqual(scopes,["mcp:read","mcp:write"],"owner actively chose write");
});
test("client-requested write is also withheld without explicit owner consent",async()=>{
 let scopes;
 const api=apiWith({completeAuthorization:async options=>{scopes=options.scope;return {redirectTo:"https://example.com/callback?code=ok"};}});
 await completeOwnerGrant(api,url,["mcp:read","mcp:write"],false);
 assert.deepEqual(scopes,["mcp:read"]);
});
test("write opt-in cannot bypass server scope allowlist or read prerequisite",async()=>{
 let scopes;
 const api=apiWith({
   parseAuthRequest:async()=>({clientId:"demo",scope:["mcp:read"]}),
   completeAuthorization:async options=>{scopes=options.scope;return {redirectTo:"https://example.com/callback?code=ok"};}
 });
 await completeOwnerGrant(api,url,["mcp:read"],true);
 assert.deepEqual(scopes,["mcp:read"]);
 const noRead=apiWith({
   parseAuthRequest:async()=>({clientId:"demo",scope:[]}),
   completeAuthorization:async options=>{scopes=options.scope;return {redirectTo:"https://example.com/callback?code=ok"};}
 });
 await completeOwnerGrant(noRead,url,["mcp:read","mcp:write"],true);
 assert.deepEqual(scopes,[]);
});
