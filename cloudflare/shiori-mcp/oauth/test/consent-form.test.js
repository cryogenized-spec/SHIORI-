import test from "node:test";
import assert from "node:assert/strict";
import {renderConsentPage,validateConsentSelections} from "../consent-form.js";

const page=()=>renderConsentPage({
 clientName:"ChatGPT",requestedScopes:["mcp:read"],nonce:"a".repeat(64)
});
const form=data=>validateConsentSelections(new URLSearchParams(data));

test("read and write have aligned, labelled checkboxes",()=>{
 const html=page();
 assert.match(html,/<div class="permission-list" role="group" aria-labelledby="permissions-heading">/);
 assert.match(html,/<input type="checkbox" name="read_access" value="yes" checked required>/);
 assert.match(html,/<input type="checkbox" name="write_access" value="yes">/);
 assert.match(html,/Read access <span class="flag">Required/);
 assert.match(html,/Write access <span class="flag">Optional/);
 assert.match(html,/Select write access separately to enable editing tools/);
 assert.match(html,/<input type="checkbox" name="approve" value="yes" required>/);
});

test("page escapes client name, retains nonce and does not contain a secret",()=>{
 const html=renderConsentPage({
  clientName:'<img src=x onerror="alert(1)">',
  requestedScopes:["mcp:read","mcp:write"],
  nonce:"a".repeat(64)
 });
 assert.ok(!html.includes("<img"));
 assert.ok(html.includes("&lt;img"));
 assert.ok(html.includes('name="nonce" value="'+ "a".repeat(64)+'"'));
 assert.match(html,/ChatGPT requested both permissions/);
 assert.ok(!html.includes("OWNER_APPROVAL_SECRET"));
});

test("read-only selection is allowed; write grant requires explicit choice",()=>{
 assert.deepEqual(form("read_access=yes&approve=yes"),{ok:true,writeApproved:false});
 assert.deepEqual(form("read_access=yes&write_access=yes&approve=yes"),{ok:true,writeApproved:true});
});

test("read checkbox is mandatory and must be unique",()=>{
 for(const params of [
  "approve=yes", "read_access=no&approve=yes",
  "read_access=yes&read_access=yes&approve=yes",
  "read_access=yes&read_access=no&approve=yes"
 ]){
  const result=form(params);
  assert.equal(result.ok,false);
  assert.match(result.error,/Read access is required/);
 }
});

test("rejects tampered write and missing final approval",()=>{
 for(const params of [
  "read_access=yes&write_access=maybe&approve=yes",
  "read_access=yes&write_access=yes&write_access=yes&approve=yes"
 ]){
  const result=form(params);
  assert.equal(result.ok,false);
  assert.match(result.error,/Invalid write permission/);
 }
 for(const params of [
  "read_access=yes", "read_access=yes&approve=no",
  "read_access=yes&approve=yes&approve=yes"
 ]){
  const result=form(params);
  assert.equal(result.ok,false);
  assert.match(result.error,/Consent not granted/);
 }
});