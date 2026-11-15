# ADR 0004 — One operation registry for local UI, remote JSON API and SHIORI MCP

**Status:** Proposed architecture, recorded 2026-11-15; **no remotely reachable SHIORI MCP or authenticated API has been implemented**.

Related: [Roadmap](../../ROADMAP.md), [ADR 0002](0002-application-ports-and-provider-boundaries.md), [ADR 0003](0003-optional-ai-companion-and-credentials.md), [Versioned operation registry](../api/operations.v1.json), [API contracts and phased scope](../api/REMOTE_OPERATIONS.md).

## Problem

SHIORI has a Rust task engine, SQLite persistence and a local development HTTP bridge to the 2D Infinite Spatial Workspace (ISW). It does not yet have a production application-service boundary, registered MCP tools, remote auth, a remote sync server, a graph/artifact registry, or connected EAI. As more manipulation is added, an AI agent must not have to mimic a pointer/drag event in a browser or send arbitrary JS, SQL or JSON to a universal unvalidated executor. Every semantic capability needs its own discoverable, scoped, typed, versioned operation.

## Decision

**Every user-visible capability should be modelled as one individually named application operation**, backed by a single Rust application-service implementation whenever the operation affects SHIORI data. A machine-readable operation catalogue is the *contract source of truth* for naming, JSON request/response schemas, permission requirements, risk classification, version and capability discovery.

Adapters may expose the same operation as:
- A **local** method called by the Rust desktop/Android clients or native bridge.
- A separately addressable authenticated **JSON-over-HTTP endpoint** `POST /api/v1/ops/{operation-id}`. Each operation has its **own route and schema**. We deliberately choose explicit JSON command endpoints over calling this resource-oriented REST; ordinary REST resources may be added later as a facade.
- An individually named **MCP tool** (e.g. `shiori_spatial_node_position_set`) declared with `inputSchema` and `outputSchema`, invoked through the protocol's **single `POST /mcp` transport endpoint**. MCP tools are **not** individual HTTP URLs. This distinction is deliberate and prevents a nonstandard MCP implementation. The current 2026-07-28 Streamable HTTP version uses POST per JSON-RPC request at that endpoint.
- A versioned **MCP Apps** UI resource for hosts that negotiate UI support; never the sole interface to the operation. The same operation must return useful text/structured data without a rich UI.

No adapter contains duplicate business logic or directly mutates canonical SQLite tables. The Rust application layer validates every request and calls domain/repository ports. `shiori-core` stays independent of HTTP, MCP and external providers. Do not use the Python local bridge as a public server or assume it supplies remote authentication.

## Semantic versus visual operations

Separate operations into *read*, *transient view*, *persistent view write*, *canonical domain write* and *external side effect*. An agent may inspect graph state, select/highlight objects, pan a view, change connector routing, or propose a layout without changing task dependencies. Persisting camera/position changes requires view-level authorization and a revision; editing a real dependency or task uses the canonical application's authorization, optimistic concurrency and audit. Link-routing style (`circuit`, `curved`, `straight`) is **presentation only**. Actual `blocks`, `contains`, `references` edges are distinct typed domain records.

A read query must never write, subscribe, run an automation or alter position. Long-running and multi-step actions (GitHub imports, analysis, large scene builds, external sync) are started as named operations and observed via separate job operations; remote work is **opt-in** and cancellable.

## JSON contract

Every operation has its own JSON-schema-validated `arguments` object with `workspace_id`, any resource ID, and typed command arguments. Reject unknown fields, unsafe coordinates, oversized strings, dangling references and invalid state transitions. Never accept arbitrary JavaScript, SQL, JSON Patch or code as an operation name/handler. A JSON string is accepted **as an encoded request document**, but it must parse into the defined JSON object; it is never dynamically executed.

All writes require `idempotency_key`, or an explicitly documented equivalent; edits and link/dependency changes require `expected_revision`. Response envelopes distinguish success, affected resource IDs, resulting revisions, warnings and provenance from failure codes. Per-actor access and workspace association are verified server side—passing `workspace_id` does not grant access.

Batch modifications have **two separate named operations**: `*.preview` computes a proposed change/diff with a short-lived revision-bound `proposal_id`; `*.apply` accepts that proposal, verifies freshness/permissions and revalidates the whole change set. Material/destructive/external effects require explicit user confirmation through the host interface. Ordinary assistant text is not permission to execute a change.

## Security and deployment

The remote server uses authenticated user-owned or self-hosted deployment. Enforce actor identity, workspace and resource scope, least privilege per operation, revocable tokens, origin checks, rate limits and payload budgets. Do not rely on CORS as authentication. MCP HTTP authorization should follow the protocol's current authorization spec. Clients cannot obtain provider API keys; Cloudflare/other backend credentials remain in server-side secrets. Automatic email replies or provider writes require additional, independently configured consent. Keep sensitive document and prompt contents out of default logs.

Offline Shiori must remain functional. For agent requests against a remote copy, responses must report freshness and connectivity; **a remote MCP cannot read unsynced data only present on an offline phone**. Sync and webhook calls do not bypass the same permission and provenance checks.

## Versioning and compatibility

- The registry is `operations.v1.json`, a **planning and validation manifest**, not evidence that endpoints exist. Every operation is marked `planned` until demonstrably implemented and passing tests.
- Stable IDs, MCP tool names and JSON schemas do not silently change. Prefer additive fields and capability discovery; use `/api/v2` and a new MCP tool name for breaking changes.
- Machine-generated MCP tool definitions and HTTP router bindings should be derived from the same registry/application descriptors, with test snapshots that fail on drift.
- Avoid one generic `run_command`, `execute_json`, or `modify_graph` tool exposed to agents. A typed **internal** dispatcher is acceptable; public contracts remain independently named and limited.

## Implementation sequence

1. **Contract-first:** inventory existing canvas and task commands and approve the registry, error vocabulary and scopes; verify every operation is uniquely named and has explicit schemas.
2. **Shared Rust application layer:** move the existing local task/position/edge access behind typed services; preserve canonical SQLite v3 and the isolated spatial sidecar v1; add identity, revision, transactions and audit for writes.
3. **Authenticated HTTP JSON adapter:** implement health/capabilities, task read/create/update, scene read, position set, and graph read first. No public binding of the legacy Python bridge.
4. **MCP Streamable HTTP adapter:** register a few proven tools with input/output schemas; test discovery and calls from an actual client. Add MCP Apps as optional UI, with graceful non-UI fallback.
5. **SH-005 inbox and SH-006 graph:** add native inbox service, provenance-linked artifacts, typed edges/backlinks, bounded retrieval and previews.
6. **SH-007 EAI + SH-008 companion:** validate scenes, add render/edit/propose tools and consent-controlled apply. Keep model-connection gateway separate from task-command authorization.
7. **External providers and automation:** ClickUp/GitHub/Gmail via read-only connectors initially, authenticated imports and explicit approved writes later.

## Proof and release gate

An MCP client must be able to discover and call separately named `tasks.get`, `spatial.scene.read`, `spatial.node.position.set` tools with the expected JSON, and see the change reflected in the existing native/browser view without mutating unrelated canonical task fields. Test invalid JSON, missing scopes, cross-workspace identifiers, stale revisions, duplicate retries, offline staleness, 5,000-node output budgets and non-UI clients. No production-ready claim without authenticated remote endpoint and actual end-to-end tests.
