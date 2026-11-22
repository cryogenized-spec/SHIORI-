# ChatGPT as a full SHIORI operator — tasks and spatial scenes

**Decision (22 November 2026).** ChatGPT should manage both real tasks and the Infinite Spatial Workspace, including constructing and rearranging diagrams, within one conversation. This is a product direction, not a claim that every operation has been implemented.

## Available now

The authenticated remote MCP has 33 live operations covering remote task CRUD, status, priority, prerequisites, scene reading/export, node positions, viewport, connector routing, layout lock and safe synchronization pilots. The registry currently describes 126 operations, of which 93 are planned.

ChatGPT may chain any number of **available typed operations** in one conversation: create tasks, connect prerequisites, arrange their visual nodes, inspect results and continue editing. No artificial separate "tasks" and "diagrams" modes. Per-call API quotas, pagination and limits remain, so large work should be chunked and checkpointed.

**Crucial:** Cloudflare D1 remains separate from the Android/local Rust SQLite store. Remote task changes are not automatically local changes. The embedded companion is draft-only, not a connected ChatGPT runtime. ChatGPT's MCP OAuth connection does not supply a separate inference API key for the embedded Android app; external model/API usage may incur separate charges.

## Execution contract

1. Discover the authenticated workspace, capabilities and tool schemas. Never execute an operation marked planned as if it were live.
2. Read only the necessary records, visual positions, prerequisite links and revisions. Keep semantic dependency edges separate from cosmetic connectors.
3. Compose a typed plan of named operations with expected revisions and a visible change summary. Ordinary reads and simple reversible view changes can proceed as authorised. Bulk, destructive, external or high-impact changes need deliberate review and approval.
4. Execute via OAuth-scoped named MCP operations with server-side validation, idempotency and optimistic concurrency. Never expose generic shell, SQL, eval or unbounded arbitrary-command tools to the model.
5. Verify affected task and spatial records after writes. On partial failure, report what completed; reconcile receipts before retrying.
6. Always identify the modified store: remote Cloudflare, local Android/Rust, or an exported offline diagram.

## A single mixed workflow available today

For "create an inspection task followed by handoff and lay them out from left to right":

- Create the two tasks with task creation operations and unique idempotency keys.
- Add the handoff prerequisite to inspection using the handoff record's current revision.
- Set each task node's visual position using the separate position revision.
- Optionally change connector style using its own independent revision.
- Reread the remote scene and task prerequisites to confirm. The operations are individually committed, not atomic as a sequence.

This workflow is already expressible through the live remote tools; it has no local Android side effects.

## Future extensions — explicit deliverables

**First-class diagrams:** non-task nodes, typed notes, diagrams, group/cluster objects, document references, relationships, provenance and backlinks. Do not create fake real tasks simply to represent drawing objects.

**Atomic multi-action preview/apply:** implement the existing planned graph-restructure, spatial-layout and scene-import preview/apply contracts. Immutable revision-bound preview diff, expiring proposal ID, explicit approval, validation of node identities and cycles, and one-store atomic execution.

**Safe device sync:** true Rust/SQLite ↔ D1 consistency, paired devices, offline queue and tombstone replay, verified conflicts, backups, and physical two-device acceptance before silent background synchronization.

**Embedded ChatGPT control surface:** honest connected state, operation plan and change previews, consent UX, execution receipts and undo where supported; retain offline use without AI.

**Extensible tools:** named, auditable, revocable, scoped integrations and cancellable long-running jobs for other data sources, with support for mixed natural-language requests.

The goal of "unlimited power" is broad composable capability, **not** unlimited costs, rate limits or permissions, or permission to take hidden destructive actions. Provider billing, quotas and approval boundaries remain visible.
