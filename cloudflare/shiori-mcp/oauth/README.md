# SHIORI OAuth 2.1 pairing and read-only sync (Phase B)

**Development status:** two new Workers are staged alongside the existing single-owner bearer alpha; **do not treat the OAuth path as connected to ChatGPT until paired and tested.**

## Why a separate authorization Worker?

Cloudflare's maintained `@cloudflare/workers-oauth-provider` (pinned to version 1.2.4) implements PKCE S256, RFC 8414/9728 discovery, authorization codes, refresh-token rotation, revocation and resource-audience binding. Two new scripts keep it independent from the already working `shiori-mcp-alpha` bearer-only Worker:

- `shiori-auth`: authorization issuer, with its own `OAUTH_KV` namespace and a **single-owner approval form**.
- `shiori-mcp-oauth`: authenticated MCP resource server, calling `shiori-auth` over a Cloudflare Service Binding. Shares the existing isolated `shiori-mcp-alpha` D1 workspace, **not the local Rust database**.

The OAuth resource Worker is **MCP-only**, audience-bound to `/mcp`. The original private-bearer Cloudflare Worker retains the dedicated JSON/HTTP routes. The OAuth resource requires `mcp:read` to discover/read and `mcp:write` for mutations. Its protected handler forwards only validated requests to the same nine Shiori operations that the bearer alpha exposes. The legacy internal auth check receives a random per-request nonce; no persistent bearer secret is shared.

### OAuth sign-in protection

The form requires an explicit opt-in, the owner approval code stored as a Cloudflare Worker secret, a short-lived CSRF cookie, same-origin POST and a five-minute pending authorization request. OAuth token issuance and PKCE are handled by the vetted library, **not our custom form**.

This is a *single-user experiment*. The owner approval code is an additional high-entropy shared secret, not a multi-user identity provider. It must not be put in a repository, browser URL, plaintext Worker var, prompt or chat message.

For repeatable local deployment, run from the repository root:

```bash
cd ~/SHIORI-
git pull --ff-only
umask 077
mkdir -p ~/.config/shiori
openssl rand -hex 32 | tr -d '\n' > ~/.config/shiori/oauth-approval-code
chmod 600 ~/.config/shiori/oauth-approval-code
npx wrangler secret put OWNER_APPROVAL_SECRET --name shiori-auth \
  < ~/.config/shiori/oauth-approval-code
```

This command requires your Cloudflare account authentication on the laptop; no credential needs to be supplied to ChatGPT. Store the approval code securely. Do not commit or upload it. Rotate the code promptly if exposed.

Enable the new Workers' `workers.dev` routes **only after** secret installation and metadata/authorization tests. The old alpha Worker need not be disabled during migration. The final OAuth URLs are:

- Issuer: `https://shiori-auth.cryogenized.workers.dev`
- Resource: `https://shiori-mcp-oauth.cryogenized.workers.dev/mcp`

OAuth client consent shows the exact client and scopes it requested. Some ChatGPT connections request only `mcp:read` despite the resource advertising both scopes. For this single-owner workspace, the consent form shows **two aligned permission checkboxes**: a checked, required `mcp:read` control that must remain selected to authorize, and an unchecked, optional `mcp:write` control for create/update operations. Both are enforced server-side. Selecting it can explicitly authorize both scopes even when the client initially asks only for read, and this choice is enforced at grant creation; leaving it unchecked issues a read-only grant. The optional write choice requires the same owner approval code and cannot be silently enabled by a client. Existing read-only connections must be reauthorized for the new grant. Consent can be revoked using the provider's revocation flow. No ChatGPT account entitlements are provided by the Worker itself.

## No silent task migration

The OAuth Workers continue to serve Cloudflare's isolated D1 task records. The native Rust/SQLite task workspace on the laptop and Android remains authoritative *on those devices*. The two datasets have not been synchronized.

Before any import, you can run a **read-only compare** from your HP OMEN:

```bash
cd ~/SHIORI-
cargo build --locked -p shiori-cli
python3 cloudflare/shiori-mcp/scripts/sync_preview.py \
  --cli target/debug/shiori-cli \
  --token-file ~/Downloads/shiori-mcp-access-token.txt
```

The script reads your local Rust task snapshot and pages through the remote **read** operation using the older private bearer token; it does not transmit task titles, notes or local IDs to the cloud. It prints count-only summaries and identity warnings, and never writes into either database.

**A title match is not an identity match.** The first real sync layer requires source IDs, versioned provenance, local queue, server revision checks, tombstones and conflict resolution, plus user-reviewed preview/apply. We will not transfer actual task content to Cloudflare without a separate explicit command/consent and a reliable rollback path.

## Deployment and tests

`npm install` and `npm run check` inside `cloudflare/shiori-mcp/oauth` produce `dist/shiori-auth.js` and `dist/shiori-resource.js` from the pinned provider. GitHub Actions compiles and checks both, runs read-only diff unit tests and uploads/commits reviewable bundle outputs.

Set `OAUTH_KV` and the owner secret only on `shiori-auth`; set `AUTH_SERVER` service binding and `DB` on `shiori-mcp-oauth`. Never add the approval secret to source control or a Wrangler `vars` entry. Preserve the original `shiori-mcp-alpha` deployment while evaluating the OAuth migration.

**Still missing before production:** a real end-to-end PKCE authorization from a permitted client, revocation test, token audience/scope negative tests on deployed Workers, account-based credential recovery/rotation, and a shared Rust/cloud reconciliation protocol. An OAuth script compiling does not prove that a client can finish login.

## Browser compatibility: OAuth form Origin

On 2026-11-15 a Firefox form submission produced `Invalid form origin.` because the original consent page set `Referrer-Policy: no-referrer`: privacy-sensitive HTML navigation POSTs may then send `Origin: null`. The consent page now uses `strict-origin`, which does not reveal the authorization URL/query string, and has an independent form-origin validator. It accepts a missing/opaque Origin **only with verified same-origin Fetch Metadata or Referrer**. Explicit foreign origins, cross-site/same-site submissions and malformed referrers are rejected. The server still verifies the short-lived hidden nonce, host-only HttpOnly SameSite cookie, KV pending request, user approval, and owner secret before issuing a grant. See `test/form-origin.test.js`.

## Failed grant diagnostics (Cloudflare 1101)

A November 15 authorization failure exposed an asynchronous error boundary: `fetch()` returned the Promise from `postAuthorize()` without `await`, which allowed rejected authorization promises to escape its `try/catch` and show Cloudflare Error 1101. The handler now awaits all routed handlers. The grant handoff reports a redacted stage identifier (`restore_request`, `lookup_client`, `create_grant`, `validate_redirect`) without logging approval codes or OAuth URLs. The pending consent KV record is only deleted after the authorization grant succeeds. The endpoint must still be tested with a real consenting client to prove the full flow; unit tests alone are not sufficient.

## 2026-11-15: authorization redirect header fix

After Shiori had successfully accepted the owner code, Cloudflare returned a generic `Authorization service unavailable` page. The post-authorization handler constructed a redirect with `Response.redirect()`, then attempted to mutate its **immutable** headers to clear the approval cookie. That throws `TypeError` per the Fetch response-header guard, *after* the OAuth grant work. The `owner-redirect.js` helper now constructs a `new Response(null, {status:302, headers:{...}})` with `Location`, secure cookie expiration, and no-store already attached. The pending KV record is deleted only after response creation. Regression tests reproduce the original `TypeError` and verify the correct 302/cookie response. A fresh owner authorization remains necessary to validate full end-to-end pairing; no existing tokens or approval secret were changed.
