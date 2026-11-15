import test from "node:test";
import assert from "node:assert/strict";
import {webcrypto} from "node:crypto";
import {ownerProof,verifyOwnerProof} from "../owner-proof.js";
if (!globalThis.crypto) globalThis.crypto=webcrypto;
const key="b7".repeat(32),challenge="c8".repeat(32);
test("same secret and challenge yield deterministic HMAC proof",async()=>{
  const proof=await ownerProof(key,challenge);
  assert.match(proof,/^[0-9a-f]{64}$/);
  assert.equal(await verifyOwnerProof(key,challenge,proof),true);
});
test("proof rejects a changed secret, altered challenge or unexpected whitespace",async()=>{
  const proof=await ownerProof(key,challenge);
  assert.equal(await verifyOwnerProof("b6".repeat(32),challenge,proof),false);
  assert.equal(await verifyOwnerProof(key,"c9".repeat(32),proof),false);
  assert.equal(await verifyOwnerProof(key,challenge,proof+"\n"),false);
});
test("normalises only edge whitespace in local and Cloudflare secret",async()=>{
  const proof=await ownerProof("  "+key+"\r\n",challenge);
  assert.equal(await verifyOwnerProof(key,challenge,proof),true);
  assert.equal(await verifyOwnerProof("  "+key+"\n",challenge,proof),true);
});
test("does not reveal actual secret bytes in a proof",async()=>{
  const proof=await ownerProof(key,challenge);
  assert.notEqual(proof,key);
  assert.notEqual(proof,challenge);
});
test("rejects invalid proof input",async()=>{
  await assert.rejects(ownerProof(key,"broken"),/Invalid proof input/);
  assert.equal(await verifyOwnerProof(key,challenge,"not a proof"),false);
});
