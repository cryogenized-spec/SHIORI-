# SHIORI OAuth 2.1 pairing and read-only sync (Phase B)

**Development status:** two new Workers are staged alongside the existing single-owner bearer alpha; **do not treat the OAuth path as connected to ChatGPT until paired and tested.**

## Why a separate authorization Worker?

Cloudflare's maintained `@cloudflare/workers-oauth-provider` (pinned to version 1.2.4) implements PKCE S256, RFC 8414/9728 discovery, authorization codes, refresh-token rotation, revocation and resource-audience binding. Two new scripts keep it independent from the already working `shiori-mcp-alpha` bearer-only Worker:

- `shiori-auth`: authorization issuer, with its own `OAUTH_KV` namespace and a **single-owner approval form**.
- `shiori-mcp-oauth`: authenticated MCP resource server, calling `shiori-auth` over a Cloudflare Service Binding. Shares the existing isolated `shiori-mcp-alpha` D1 workspace, **not the local Rust database**.

The OAuth resource Worker requires `mcp:read` to discover/read and `mcp:write` for mutations. Its protected handler forwards only validated requests to the same nine Shiori operations that the bearer alpha exposes. The legacy internal auth check receives a random per-request nonce; no persistent bearer secret is shared.

### OAuth sign-in protection

The form requires an explicit opt-in, the owner approval code stored as a Cloudflare Worker secret, a short-lived CSRF cookie, same-origin POST and a five-minute pending authorization request. OAuth token issuance and PKCE are handled by the vetted library, **not our custom form**.

This is a *single-user experiment*. The owner approval code is an additional high-entropy shared secret, not a multi-user identity provider. It must not be put in a repository, browser URL, plaintext Worker var, prompt or chat message.

For repeatable local deployment, run from the repository root:

```bash
cd ~/SHIORI-
git pull --ff-only
umask 077
mkdir -p ~/.config/shiori
openssl rand -base64 48 > ~/.config/shiori/oauth-approval-code
chmod 600 ~/.config/shiori/oauth-approval-code
npx wrangler secret put OWNER_APPROVAL_SECRET --name shiori-auth \
  < ~/.config/shiori/oauth-approval-code
```

This command requires your Cloudflare account authentication on the laptop; no credential needs to be supplied to ChatGPT. Store the approval code securely. Do not commit or upload it. Rotate the code promptly if exposed.

Enable the new Workers' `workers.dev` routes **only after** secret installation and metadata/authorization tests. The old alpha Worker need not be disabled during migration. The final OAuth URLs are:

- Issuer: `https://shiori-auth.cryogenized.workers.dev`
- Resource: `https://shiori-mcp-oauth.cryogenized.workers.dev/mcp`

OAuth client consent should show the exact client and granted scopes. Check the requested source before consenting. Consent can be revoked using the provider's revocation flow. No ChatGPT account entitlements are provided by the Worker itself.

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
