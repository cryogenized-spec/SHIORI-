import test from "node:test";
import assert from "node:assert/strict";
import { isTrustedConsentRequest } from "../form-origin.js";

const issuer = "https://shiori-auth.cryogenized.workers.dev";
function request(headers = {}) {
  return new Request(issuer + "/authorize", { method: "POST", headers, body: "nonce=placeholder" });
}
test("normal same-origin form is accepted", () => {
  assert.equal(isTrustedConsentRequest(request({Origin:issuer,"Sec-Fetch-Site":"same-origin"}),issuer),true);
});
test("Firefox privacy/no-referrer form with Origin null and same-origin Fetch Metadata is accepted", () => {
  assert.equal(isTrustedConsentRequest(request({Origin:"null","Sec-Fetch-Site":"same-origin"}),issuer),true);
});
test("missing Origin can use same-origin Fetch Metadata or valid same-origin Referer", () => {
  assert.equal(isTrustedConsentRequest(request({"Sec-Fetch-Site":"same-origin"}),issuer),true);
  assert.equal(isTrustedConsentRequest(request({Referer:issuer+"/authorize"}),issuer),true);
});
test("reject forged origins even if Fetch Metadata says same-origin", () => {
  assert.equal(isTrustedConsentRequest(request({Origin:"https://evil.example","Sec-Fetch-Site":"same-origin"}),issuer),false);
  assert.equal(isTrustedConsentRequest(request({Origin:"https://shiori-auth.cryogenized.workers.dev.evil.example"}),issuer),false);
});
test("reject cross-site, sibling subdomains, null without independent origin proof", () => {
  assert.equal(isTrustedConsentRequest(request({Origin:"null","Sec-Fetch-Site":"cross-site"}),issuer),false);
  assert.equal(isTrustedConsentRequest(request({Origin:"null","Sec-Fetch-Site":"same-site"}),issuer),false);
  assert.equal(isTrustedConsentRequest(request({Origin:"null"}),issuer),false);
  assert.equal(isTrustedConsentRequest(request({}),issuer),false);
});
test("reject suspicious/malformed referrers", () => {
  assert.equal(isTrustedConsentRequest(request({"Sec-Fetch-Site":"same-origin",Referer:"https://evil.example/page"}),issuer),false);
  assert.equal(isTrustedConsentRequest(request({"Sec-Fetch-Site":"same-origin",Referer:"not-a-url"}),issuer),false);
});
