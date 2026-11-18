# SHIORI Cloudflare MCP — single-owner alpha (18 November 2026)

**Verified live before S2 promotion:** 23 runnable operations. The branch implements four additional S2 tools (27 total in source; 120 versioned contracts; 93 planned), pending database migration, CI and deployment. Both the legacy bearer Worker `shiori-mcp-alpha` and OAuth-protected MCP resource `shiori-mcp-oauth` are deployed. ChatGPT has successfully authorized `mcp:read` and optional `mcp:write`, created demo tasks and read seven native prerequisite edges. Cloudflare D1 and Rust/SQLite **remain isolated**.

## Current limitations

- Cloudflare D1 contains **isolated remote tasks and visual view state**; there is **no automatic synchronisation** with the local Rust/SQLite task store. Never claim remote tasks are local tasks.
- The Worker does not access GitHub, ClickUp, Gmail or an AI provider.
- The legacy `shiori-mcp-alpha` service accepts an owner secret bearer token. The separate `shiori-mcp-oauth` resource uses OAuth 2.1 / PKCE with `shiori-auth`; owner consent requires read and optionally grants write. These are **two different authentication paths** to the same isolated D1 operations.
- No multi-user tenancy, shared Cloudflare hosting, third-party identities or public unauthenticated tools.
- No durable live EAI renderer, graphical scene hosting or Shiori inbox yet.

## Live tools and JSON operations

The **23** verified deployed operations, prior to S2 promotion, are:
- System: `system.capabilities.read`, `system.operations.list`.
- Tasks: `tasks.list`, `tasks.get`, `tasks.create`, `tasks.update`, `tasks.status.set`, `tasks.delete` (soft delete), `tasks.restore`, `tasks.priority.set`.
- Graph: `tasks.dependencies.list`, `tasks.dependencies.add`, `tasks.dependencies.remove`.
- Spatial: `spatial.scene.read`, `spatial.scene.export`, `spatial.node.position.read`, `spatial.node.position.set`, `spatial.viewport.read`, `spatial.viewport.save`, `spatial.layout.lock.set`, `spatial.edge.style.set`, `spatial.node.inspect`.
- Read-only reconciliation: `sync.manifest.read` (identity/version/tombstone pages, not an atomic snapshot).

Four new **S2 first-import pilot** operations are implemented in the source but must pass release gates and deployment before being considered live: `sync.device.pair`, `sync.import.preview`, `sync.import.apply`, `sync.import.receipt.read`. They do not authorize automatic replication. Details in [S2](../../docs/engineering/RUST_CLOUDFLARE_SYNC_S2.md).

The remaining **93** registry contracts are documentation only; the server does not advertise or execute them as tools. Native Rust SQLite sync, inbox, artefacts, jobs, model providers and production multi-user identity are not implemented remotely.

Each operation is also available at `POST /api/v1/ops/<dot-separated-id>` with the same JSON input schema. MCP uses one `POST /mcp` JSON-RPC Streamable HTTP endpoint with individually named tools `shiori_<underscore_name>`.

`GET /health` returns public, **non-sensitive** status only. All task data, list/discovery, operations and MCP calls require a valid bearer credential on the legacy worker or a scoped OAuth credential on the protected MCP worker. `workspace_id` is `personal` for this single-user alpha.

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

The Worker accepts at most 32 KiB per JSON request, caps result pagination, rejects unsafe coordinates and revision conflicts, uses conditional SQLite writes and records idempotency keys for supported write operations. It has a simple per-minute owner rate limit. Production multi-user security, broader quota controls and comprehensive sync/conflict reconciliation remain future work.

## Deployment

The owner may provision `shiori-mcp-alpha` D1 and run `schema.sql` once through Cloudflare D1 tools, upload `src/worker.js` as an ES module Worker with `DB` D1 binding and plaintext `WORKSPACE_ID=personal`, and set the **secret** `SHIO_AUTH_TOKEN` using Cloudflare's Workers Secrets. Activate the Worker subdomain only after the secret and schema are in place.

For local tests, Node 22 or newer:

```bash
cd cloudflare/shiori-mcp
npm test
```

Tests use a disposable in-memory SQLite database and do not touch Cloudflare or real tasks.

## Complete operation schema discovery

Shiori has **115 operation contracts** in `docs/api/operations.v1.json`.
The Cloudflare MCP makes **all 115 full contracts discoverable** without
presenting unimplemented commands as runnable. The registry includes
input and output JSON Schemas, operation ID, scope, effect, approval
requirements, phase and actual availability.

- `resources/list` advertises `shiori://operations/v1`.
- `resources/read` on that URI returns the **entire source-aligned registry**.
- `resources/templates/list` advertises `shiori://operations/v1/{operation_id}`;
  `resources/read` on, for example, `shiori://operations/v1/tasks.delete`
  returns the complete single-operation schema (including its actual implemented/planned status).
- The implemented `shiori_system_operations_list` tool provides paginated
  access with `workspace_id`, `cursor`, `limit`, and optional
  `availability` or exact `operation_id` lookup. It returns full contracts,
  not merely names.
- `tools/list` deliberately advertises **only the 22 runnable operations**:
  the original operations plus guarded CRUD, graph and spatial operations. Unsupported operations
  are never executed; they cannot be called merely because their schema
  exists in the catalog.

OAuth `mcp:read` is sufficient to inspect the catalog. All registry
requests remain authenticated and workspace-scoped. Catalog discovery
does not grant permissions, implement missing Rust/cloud sync, execute
planned destructive operations or upgrade an existing OAuth token.

For clients that support MCP resources, use `resources/read` for the entire
contract or one named operation. For clients that expose only tools,
use `shiori_system_operations_list`; its `operation_id` filter is the
quickest way to inspect one schema. **Do not request unimplemented
operations through `tools/call`.**

The worker bundles a snapshot of the registry for standalone Cloudflare
deployment. After editing the canonical JSON, run
`python3 cloudflare/shiori-mcp/scripts/sync_operation_catalog.py`
to refresh its embedded snapshot. Tests compare the deployed snapshot
against the canonical registry and fail on drift.

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
write-action approval policy or plan restrictions. The OAuth owner consent form now also
provides a separate, unchecked **Enable write access** checkbox. The owner must
explicitly select it before a grant includes `mcp:write` — including when the
client requests only `mcp:read` or requests both scopes. Unchecked means
read-only. Reconnect/re-authorize to replace an existing read-only grant.

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
   and its mutations exercised. A soft-delete and restore MCP tool now exists, with version and idempotency guards.

The absent Rust/SQLite ↔ D1 synchronization is **not fixed by this patch**.
Keep local and remote data separate until a versioned, opt-in sync protocol
with tombstones, source IDs, conflict resolution and rollback is implemented.

## Next engineering phases

1. Implement standards-compliant OAuth/PKCE pairing for ChatGPT and similar remote clients; use explicit user identity and revocable sessions.
2. Introduce a Rust application-service facade over canonical local tasks and a well-defined authenticated sync protocol. Prove field mapping, conflicts, tombstones, revisions and offline queue replay.
3. Add live EAI/MCP Apps UI resources and typed graph/inbox operations only as Rust-backed services become available. Use the 115-operation registry as a planning inventory, not a dynamic arbitrary-execution endpoint.

## Native cloud prerequisite links (2026-11-17)

`tasks.dependencies.add` / `shiori_tasks_dependencies_add` connects one active Cloudflare D1 task to an active prerequisite, using the dependent task's current version in `expected_revision` and a unique `idempotency_key`. It rejects self-links, duplicates, inactive/missing tasks, stale versions and cycles (including indirect cycles) through an atomic SQL check; successful writes increment the dependent task revision and appear in `tasks.dependencies.list` and spatial `scene.edges` as `blocks` links. This does **not** import local Rust edges or synchronize offline tasks. The user has approved linking the eight clearly marked dummy tasks only, and broader graph edits remain reviewable.

## Expanded MCP task + spatial operations (2026-11-17)

The isolated Cloudflare D1 worker now implements `tasks.update`, `tasks.delete` (soft tombstone), `tasks.restore`, `tasks.priority.set`, `tasks.dependencies.remove`, `spatial.node.position.read`, `spatial.viewport.read`, `spatial.viewport.save`, `spatial.layout.lock.set`, `spatial.node.inspect`, and bounded `spatial.scene.export`. Every mutation requires owner-scoped OAuth write permission or a valid legacy bearer, a fresh revision (where applicable), and a unique idempotency key. Task deletion never physically purges rows. The host should request explicit confirmation for destructive actions. This does not perform Rust/SQLite cloud synchronization.
