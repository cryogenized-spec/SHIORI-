import test from "node:test";
import assert from "node:assert/strict";
import {normalizeApprovalInput} from "../approval-input.js";

test("accepts exact 64-character owner codes unchanged",()=>{
  const code="1a".repeat(32);
  assert.equal(normalizeApprovalInput(code),code);
});
test("strips accidental spaces, tabs, CRLF from clipboard pastes",()=>{
  const code="a7".repeat(32);
  assert.equal(normalizeApprovalInput("  "+code+"\r\n\t "),code);
});
test("never changes internal characters or case",()=>{
  const code="aBcD".repeat(16);
  assert.equal(normalizeApprovalInput(code),code);
  assert.notEqual(normalizeApprovalInput("a"+" "+code.slice(1)),code);
  assert.notEqual(normalizeApprovalInput(code.toUpperCase()),code);
});
test("does not treat missing input as a valid credential",()=>{
  assert.equal(normalizeApprovalInput(null),"");
  assert.equal(normalizeApprovalInput(undefined),"");
  assert.equal(normalizeApprovalInput({}),"");
});
