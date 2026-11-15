# SHIORI Remote Operations — v1 contract plan

**Status: planned, not deployed.** Last reviewed 2026-11-15. See [machine-readable registry](operations.v1.json) and [ADR 0004](../adr/0004-remote-operation-registry-and-mcp.md).

This document freezes the **shape of the integration**, not the eventual release of all 94 operations. The registry is deliberately wide enough to cover the full ISW vision; only a small proven Phase A subset is needed to open a real MCP connection. `availability: planned` means there is currently **no supported remote route or MCP tool** for that entry. The local Python development bridge is not a production API.

## One operation, two remote faces

| Application operation | Dedicated JSON/HTTP endpoint | Independently named MCP tool |
| --- | --- | --- |
| `tasks.get` | `POST /api/v1/ops/tasks.get` | `shiori_tasks_get` |
| `spatial.scene.read` | `POST /api/v1/ops/spatial.scene.read` | `shiori_spatial_scene_read` |
| `spatial.node.position.set` | `POST /api/v1/ops/spatial.node.position.set` | `shiori_spatial_node_position_set` |
| `spatial.edge.style.set` | `POST /api/v1/ops/spatial.edge.style.set` | `shiori_spatial_edge_style_set` |
| `graph.edges.create` | `POST /api/v1/ops/graph.edges.create` | `shiori_graph_edges_create` |
| `graph.restructure.preview` | `POST /api/v1/ops/graph.restructure.preview` | `shiori_graph_restructure_preview` |
| `graph.restructure.apply` | `POST /api/v1/ops/graph.restructure.apply` | `shiori_graph_restructure_apply` |
| `retrieval.context.fetch` | `POST /api/v1/ops/retrieval.context.fetch` | `shiori_retrieval_context_fetch` |
| `eai.object.add` | `POST /api/v1/ops/eai.object.add` | `shiori_eai_object_add` |

This HTTP API is **explicit action-oriented JSON-over-HTTP**, rather than traditional resource-oriented REST; it offers one path for each operation as requested. **MCP itself exposes only `POST /mcp`**, carrying standard JSON-RPC requests. Each tool within that MCP server has a unique name and typed schema. Do not create a nonstandard separate HTTP URL for each MCP tool. UI-capable hosts can additionally use negotiated MCP Apps `ui://` resources. Hosts without UI still receive structured results.

## Operation families and scope

| Family | Responsibilities | Data ownership |
| --- | --- | --- |
| `system` | Discover capabilities, schemas and available tools | Remote adapter |
| `tasks` | Create, read, update, status and real prerequisites | Canonical Rust task domain |
| `spatial` | View scene, camera, position, lock, zoom, routing and groups | Separately versioned view state |
| `inbox` | Capture, triage, convert, archive and retrieve | Independent SH-005 domain |
| `artifacts` | Notes, documents, attachment references and typed entities | Artefact registry over domain aggregates |
| `graph` | Relationships, backlinks, bounded traversals, impact/restructure | Typed graph domain |
| `retrieval` | Indexed search, deterministic context budget and source evidence | Bounded query projections |
| `eai` | Validated polygonal/illustrative scenes, focus, links, animation | Derived scene, not task graph |
| `companion` | Optional dock, threads, model capability/preferences and user messages | Separate user settings/chat store |
| `automations` | Inspected rules, dry-run, opt-in creation and execution | Service with explicitly granted connectors |
| `providers` | GitHub trees, ClickUp imports and proposed sync | Explicit provider adapter |
| `jobs` | Poll/cancel long-running actions | Authenticated background job service |

All query and mutation operations remain accessible to *ordinary software* via the application service. AI and MCP are clients of that service—not prerequisites.

## Phased scope

**Phase A — first proven end-to-end vertical slice.** Build a Rust application-service facade around existing tasks, dependencies, SQLite sidecar and live ISW scene, plus authenticated `system.capabilities.read`, `tasks.list/get/create`, `tasks.status.set`, `spatial.scene.read`, `spatial.node.position.set`, `spatial.edge.style.set`. Make each command available through a separately routed JSON endpoint and independently registered MCP tool, with a real client test. Preserve local/offline functionality and the canonical task schema v3.

**Phase B — first-class objects and relationships.** Complete SH-005 inbox persistence, typed artefact references, attachments, graph edges and backlinks, bounded librarian/context queries, cycles/impact previews, visual layout batches, explicit graph restructure preview/apply. Preview must be non-mutating; apply is separately audited.

**Phase C — expressive scenes and integrated assistant.** Validate versioned `EaiScene` JSON, render polygonal and layered objects, offer scene-only additions/modifications, optional large visual stage and text fallback. Add persistent chat threads, movable assistant dock, model-aware preferences and optional user-owned provider backend. The built-in assistant and ChatGPT-through-MCP share application permissions, not API keys.

**Phase D — external workflows.** Add read-only GitHub source graph, ClickUp import/sync previews, secure inbox events, opt-in email automation and job processing. Explicit user review is required before modifying external records or sending messages.

These are **implementation phases**, not promises that 94 remote tools will be enabled immediately. MCP tool discovery should expose *only actually implemented and authorized operations*; the full planning manifest is not the live tool list.

## JSON request and response — planned wire format

A model/automation can call the individually named operation with a structured object. This is an **example contract**, not an endpoint already reachable:

```http
POST /api/v1/ops/spatial.node.position.set
Authorization: Bearer <revocable-user-token>
Content-Type: application/json
```

```json
{
  "workspace_id": "workshop",
  "node_id": "task-104",
  "x": 640,
  "y": 320,
  "expected_revision": 7,
  "idempotency_key": "018e95f6-7cf0-7356-9979-bd30e23db30a"
}
```

```json
{
  "ok": true,
  "operation_id": "spatial.node.position.set",
  "data": {
    "position": {"node_id":"task-104","x":640,"y":320,"revision":8}
  }
}
```

The corresponding MCP call uses `tools/call` with `name: "shiori_spatial_node_position_set"` and these same validated arguments, travelling over the **single MCP endpoint** as JSON-RPC. That operation changes only view-state coordinates. It cannot create a task or a prerequisite.

For a **real relationship** the agent instead calls `graph.restructure.preview` or a dedicated reviewed `graph.edges.create` flow, receives an evidence-backed diff, and then (after explicit user approval) calls `graph.restructure.apply` with the issued `proposal_id`, expected revision and a unique idempotency key.

A visual selection, double-tap zoom/focus or assistant dock command may require a currently attached, authorized **UI session**. Headless MCP calls cannot move the camera on someone's disconnected or unaffiliated screen; they should return `UNAVAILABLE`, not pretend success.

## Implementation invariants

- **One identity/permissions boundary.** Every operation validates real actor, workspace and resource access server side. `workspace_id` in a JSON object is not an authorization grant.
- **JSON object, not free-form code.** Validate JSON Schema; refuse arbitrary JS, SQL and unrecognized property names. All strings/attachments/remote text are untrusted. Escaped JSON text can be parsed, but never evaluated.
- **Typed results and errors.** The registry defines success schemas; failure envelope uses named codes such as `VALIDATION_FAILED`, `FORBIDDEN`, `CONFLICT`, `UNAVAILABLE`, and `PRECONDITION_REQUIRED`.
- **Separate view and domain writes.** Pan, zoom, marker palette and connector routing never change canonical dependencies. A layout lock blocks accidental UI drag, **not** authorized explicit domain commands.
- **Review and repeat safety.** Material graph edits, conversions, destructive changes and external effects use previews or explicit confirmation, revisions and idempotency. The audit record identifies the actor and effects.
- **Bounded retrieval and provenance.** Queries paginate, cap result/scene size and return source IDs, freshness and uncertainty. Never assemble an unbounded model context.
- **Independent offline behaviour.** Shiori works without the remote server and without any LLM subscription. Remote data can be stale; signal it.
- **Security/cost.** No provider secret in JSON, scene, MCP tool arguments or client logs. Use user-owned secrets backend, least privilege and budget/rate limiting; don't expose the development Python bridge to the Internet.
- **Compatibility.** Additive registry versioning and tool/route name tests. Breaking changes get new versioned operations rather than silent schema changes.

## Concrete acceptance checklist before enabling the first remote MCP

1. Register and validate an initial **small** operation subset against actual Rust services, not mock UI state.
2. Verify separate HTTP route names and MCP tool discovery correspond to the same service command and JSON Schema.
3. Prove `tasks.get` and `spatial.scene.read` return canonical data; `spatial.node.position.set` changes **only** the sidecar and produces a revisioned response.
4. Exercise authentication, unauthorised workspace IDs, stale revision conflicts, duplicate request retries, payload limits and incorrect/extra input properties.
5. Test ChatGPT or another MCP client against a reachable endpoint; verify the optional rich scene can be rendered where supported and a text/JSON fallback exists.
6. Record the CI run and release artifacts. Mark registry entries `available` **only after** real integration tests succeed.

**Bottom line:** Implement the *service and operation contracts first*, and treat both the immersive UI and MCP as two clients of the same actual Shiori data model. New operations can then be added without inventing a separate AI-specific task manager.
