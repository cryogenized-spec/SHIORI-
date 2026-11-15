# Shiori Cloudflare MCP — Phase A

This module is the first **remotely deployed, single-owner MCP server** for Shiori. The Worker exposes a **nine-operation subset** of the [113 planned operations](../../docs/api/operations.v1.json). It is a security-gated cloud alpha, not a substitute for the Rust local task database. GitHub Actions verified live `/health` (200) and unauthenticated `/mcp` rejection (401), using Cloudflare's recommended descriptive User-Agent; external *authenticated* tool calls remain to be validated.

## Current limitations

- Cloudflare D1 contains **isolated remote tasks and visual view state**; there is **no automatic synchronisation** with the local Rust/SQLite task store. Never claim remote tasks are local tasks.
- The Worker does not access GitHub, ClickUp, Gmail or an AI provider.
- This first authentication mechanism is a **long random bearer token** stored as a Cloudflare Worker secret. It is not OAuth. Many chat clients require OAuth to connect a custom remote MCP server; implement OAuth pairing separately before claiming ChatGPT app integration is complete.
- No multi-user tenancy, shared Cloudflare hosting, third-party identities or public unauthenticated tools.
- No durable live EAI renderer, graphical scene hosting or Shiori inbox yet.

## Live tools and JSON operations

`system.capabilities.read`, `tasks.list`, `tasks.get`, `tasks.create`, `tasks.status.set`, `tasks.dependencies.list`, `spatial.scene.read`, `spatial.node.position.set`, `spatial.edge.style.set`.

Each operation is also available at `POST /api/v1/ops/<dot-separated-id>` with the same JSON input schema. MCP uses one `POST /mcp` JSON-RPC Streamable HTTP endpoint with individually named tools `shiori_<underscore_name>`.

`GET /health` returns public, **non-sensitive** status only. All task data, list/discovery, operations and MCP calls require the bearer token. `workspace_id` is `personal` for this single-user alpha.

Example authenticated API call:

```bash
curl -X POST https://YOUR-WORKER.workers.dev/api/v1/ops/tasks.list \
  -H "Authorization: Bearer $SHIORI_MCP_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"workspace_id":"personal","limit":10}'
```

Example MCP tools/list:

```bash
curl -X POST https://YOUR-WORKER.workers.dev/mcp \
  -H "Authorization: Bearer $SHIORI_MCP_TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## Verify an authenticated live connection

The repository includes a **read-only** Python smoke client. After obtaining the private owner token on your own device:

```bash
python3 cloudflare/shiori-mcp/scripts/smoke_client.py --token-file /path/to/shiori-mcp-access-token.txt
```

It checks the live health endpoint, authenticated MCP initialize, tools/list, actual capability invocation and an empty or populated remote task list. It uses Cloudflare's recommended descriptive User-Agent to avoid Browser Integrity Check error 1010 on `workers.dev`. The token is never printed. This smoke test is necessary because the CI runner cannot receive the owner's Cloudflare secret; CI only tests live unauthenticated denial and simulated authenticated operations.

## Data and security

Shiori's Cloudflare Worker is deployed into **the owner's Cloudflare account**, using a separate D1 database, not the existing ClickUp or Google Master Workers/databases. Secrets stay in Worker secret bindings and are never committed. The Cloudflare Worker rejects requests lacking its bearer credential, unexpected JSON fields, unsupported operations and different workspaces.

The Worker accepts at most 32 KiB per JSON request, caps result pagination, rejects unsafe coordinates and revision conflicts, uses conditional SQLite writes and records idempotency keys for supported write operations. It has a simple per-minute owner rate limit. Production multi-user security, broader quota controls, OAuth and comprehensive sync/conflict reconciliation remain future work.

## Deployment

The owner may provision `shiori-mcp-alpha` D1 and run `schema.sql` once through Cloudflare D1 tools, upload `src/worker.js` as an ES module Worker with `DB` D1 binding and plaintext `WORKSPACE_ID=personal`, and set the **secret** `SHIO_AUTH_TOKEN` using Cloudflare's Workers Secrets. Activate the Worker subdomain only after the secret and schema are in place.

For local tests, Node 22 or newer:

```bash
cd cloudflare/shiori-mcp
npm test
```

Tests use a disposable in-memory SQLite database and do not touch Cloudflare or real tasks.

## OAuth MCP repair and write rollout (2026-11-15)

The OAuth resource (`shiori-mcp-oauth`) forwards authenticated `/mcp`
calls to the same operations as the legacy `shiori-mcp-alpha` Worker.
**Owner scope discovery:** Shiori's single-owner resource now advertises
`mcp:read mcp:write` as its initial requested scopes, because ChatGPT's
first authorisation previously requested `mcp:read` only and write step-up
was not completing. The owner consent screen must explicitly show both
before the user approves. This changes initial authorisation for new
connections; existing grants are **not** silently upgraded. A token
containing `mcp:read` only remains valid for read tools, and writes still
require `mcp:write`. This does not override ChatGPT's independent
write-action approval policy or plan restrictions.

`system.capabilities.read` now reports **the actual credential context**:
`oauth: true`, `authentication: oauth2.1-pkce`, and the granted read/write
scopes for OAuth; the separate legacy endpoint still reports bearer mode.
Do not interpret a listed write tool as permission to invoke it. OAuth
checks `mcp:write` on every mutation, and a read-only grant is denied.

All four write operations use a SHA-256 fingerprint of the canonical
operation ID and arguments (excluding only the idempotency key).
Reusing the same `workspace_id / operation_id / idempotency_key` with a
different request now returns HTTP 409 `IDEMPOTENCY_CONFLICT`.
MCP tool failures include `isError: true` **and** structured
`{ok:false,error:{code,message,http_status,retryable}}` content.
Some MCP clients still choose their own error labels; callers should
inspect `structuredContent.error.code`.

**Deployment order is mandatory for an existing D1 database:**

1. Back up the D1 database; do **not** clear `remote_tasks` or `idempotency`.
2. Run `migrations/0001_idempotency_request_hash.sql` **once** against
   the `shiori-mcp-alpha` D1 database. Fresh installations instead use
   the updated `schema.sql`.
3. Verify the new column exists. Existing rows have `request_hash=NULL`
   and are deliberately **not replayable**; clients must submit a fresh
   idempotency key for a new attempt, after reconciling any previous result.
4. Deploy the revised `src/worker.js` to the legacy bearer Worker and
   rebuild/deploy the OAuth `dist/shiori-resource.js` bundle from the same
   commit. Avoid mixing old and new Worker versions during client writes.
5. Run automated tests (`npm test` in `cloudflare/shiori-mcp`,
   and `npm run check` in `cloudflare/shiori-mcp/oauth`), then verify
   live `system.capabilities.read` with an owner OAuth session.
6. Verify a **read-only grant** receives `insufficient_scope` on a
   mutation. For an owner write grant, begin with a deliberately invalid
   request to test the validation/error path without inserting task data.
   Only after that should a user-approved disposable task be created
   and its mutations exercised. There is still no task-deletion MCP tool.

The absent Rust/SQLite ↔ D1 synchronization is **not fixed by this patch**.
Keep local and remote data separate until a versioned, opt-in sync protocol
with tombstones, source IDs, conflict resolution and rollback is implemented.

## Next engineering phases

1. Implement standards-compliant OAuth/PKCE pairing for ChatGPT and similar remote clients; use explicit user identity and revocable sessions.
2. Introduce a Rust application-service facade over canonical local tasks and a well-defined authenticated sync protocol. Prove field mapping, conflicts, tombstones, revisions and offline queue replay.
3. Add live EAI/MCP Apps UI resources and typed graph/inbox operations only as Rust-backed services become available. Use the 113-operation registry as a planning inventory, not a dynamic arbitrary-execution endpoint.
