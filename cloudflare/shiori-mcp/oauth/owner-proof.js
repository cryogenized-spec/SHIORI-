/** Short-lived incident diagnostic: never expose the owner secret or its hash.
 * The requesting device computes HMAC-SHA256(secret, fresh random challenge)
 * locally. The Worker recomputes it from the installed secret and returns
 * only a boolean. Feature-gate this handler, then disable after diagnosis.
 */
export async function ownerProof(secret, challenge) {
  if (typeof secret !== "string" || !secret || typeof challenge !== "string" ||
      !/^[0-9a-f]{64}$/.test(challenge)) throw Error("Invalid proof input");
  const encoder=new TextEncoder();
  const key=await crypto.subtle.importKey(
    "raw",encoder.encode(secret.trim()),{name:"HMAC",hash:"SHA-256"},false,["sign"]
  );
  const signature=new Uint8Array(await crypto.subtle.sign("HMAC",key,encoder.encode(challenge)));
  return Array.from(signature,b=>b.toString(16).padStart(2,"0")).join("");
}
export async function verifyOwnerProof(secret,challenge,proof) {
  if(typeof proof!=="string"||!/^[0-9a-f]{64}$/.test(proof))return false;
  const expected=await ownerProof(secret,challenge);
  let diff=0;
  for(let i=0;i<64;i++)diff|=expected.charCodeAt(i)^proof.charCodeAt(i);
  return diff===0;
}
