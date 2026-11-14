# ADR 0002 — Application ports, universal inbox and provider boundaries

Status: **Accepted as an architectural baseline (2026-11-14); implementation pending**

Supersedes: none. Complements [ADR 0001](0001-rust-core-sqlite.md) and [the SHIORI roadmap](../../ROADMAP.md).

## Problem

SHIORI is local-first, but will acquire an inbox, deterministic scheduling, multiple native clients, an authenticated MCP interface, a REST API and external provider connections. If any adapter becomes the authoritative task model, adds direct SQL writes or embeds ClickUp-specific concepts in the core, every new feature will require invasive rewrites.

The requirement confirmed on 2026-11-14 is that ChatGPT use **SHIORI's MCP** to manage SHIORI-native inbox items and tasks, including workflows that ClickUp Serviteur cannot expose. A separate optional integration synchronizes supported ClickUp resources over its public REST API. SHIORI must not claim access to ClickUp's proprietary notification Inbox.

## Decision: ports and adapters, not a giant application module

The module names below describe *responsibilities*, not existing code or a requirement to create empty crates now.

```text
          Android / Web / CLI / REST / MCP / automations
                          |
                    application API
          auth + command validation + transactions
               /          |           \
             tasks       inbox      scheduling
               \          |           /
             pure domain policies and types
                          |
              repository / change-log ports
                    /             \
                SQLite       future sync server
                          |
                provider integration port
                    /             \
             ClickUp REST    future providers
```

1. **Pure domain:** `shiori-core` owns SHIORI-native identifiers, task/inbox state machines, invariants, validation and deterministic rules. No ClickUp API types, network, SQL, UI, MCP, tokens or hosting services in this crate. Tasks and inbox entries are **different aggregate types**.
2. **Application/service layer:** A dedicated application API (in a cohesive future module, not necessarily a new crate immediately) coordinates user intent, identity, scope checks, authorization, transaction boundaries, audit/change emission and repository ports. Its typed commands and queries are the only supported access path for external adapters. No application query may unexpectedly write or reschedule.
3. **Persistence:** SQLite adapters implement repository/change-log contracts, never policy. Keep versioned migrations, reliable backups, soft-delete tombstones and optimistic revision checks. A failed command must not leave partially mutated state.
4. **Interfaces:** Android, desktop/web, CLI, REST, MCP and automation remain thin adapters translating input/output to the same application commands and queries. UI views are projections, not alternative databases; MCP tools are not service implementations.
5. **Integration:** external task-provider adapters implement a provider-port contract (discover/read changes, fetch canonical remote resources, propose outbound changes and report capabilities). They cannot modify domain records through direct SQL or bypass workspace authorization. No mandatory provider or network account.
6. **Sync:** change capture, deduplication, retries, conflict resolution and mapping are separate from both local domain edits and remote provider transport. Remote webhook events are hints to refresh state, not proof that a complete or trusted current task record was supplied. Process verified signatures and recover from missed/out-of-order events.

## First-class inbox contract (SH-005)

SHIORI-owned `InboxItem` has a stable SHIORI ID, owner/scope, captured/updated timestamps, revision, content or attachment references, provenance, triage state and optional linked task/memo/follow-up IDs. The exact schema is an M2 implementation decision; the following are **required invariants**:

- Capture does not create a task, push to ClickUp, publish an attachment or schedule time without a distinct reviewed action.
- An inbox item can be collected, reviewed/triaged, converted or linked, and archived, without silently discarding the source item. Conversion preserves a backlink for traceability.
- State transitions and revisions are validated atomically; duplicate conversion requests do not produce duplicate tasks.
- Source provenance identifies a SHIORI capture, OCR, import or provider event without treating provider-authored content as trusted instructions for an AI agent.
- Inbox content may contain sensitive information; user permissions, redacted logs, secure storage and least-privilege tool scopes apply.

## Provider identity and data-loss prevention

Every remote object maps to a composite identity `(provider, external_account, external_workspace, resource_kind, external_id)`, linked to a stable SHIORI record. Never use task titles, human-readable URLs, or timestamps alone as identity. Track source URL (when safe), last confirmed refresh, provider revision/etag or equivalent where available, local revision, mapping status and any unmapped fields. There must be a clear distinction between a SHIORI-owned item, a read-only imported record and an editable synchronised record.

Outbound commands must use per-operation idempotency keys and explicit field patches. Concurrent local/remote changes must **surface conflicts** rather than silently prefer whichever value arrived last. Keep delete tombstones and never resurrect removed records after a delayed event. Provide reconciliation after offline periods and webhook loss. Sync status includes a visible `offline / stale / syncing / synced / conflict / error` projection; this does not require implementing each status before the corresponding engine exists.

Field mapping must document unsupported types and preserve their original representation where safe. Unsupported provider fields are not silently erased on an outbound update.

## MCP and security boundary

- Typed operations for `inbox.list`, `inbox.get`, `inbox.capture`, `inbox.triage`, `inbox.convert`, `inbox.archive`, `inbox.link` are an **intended capability catalogue**, not currently deployed tool names.
- REST, MCP and UI must call the same authorized service path. Each exposed operation has explicit schema, user/workspace scope, pagination, revision preconditions and structured errors.
- Scopes distinguish read, capture, edit/triage, conversion, provider-write and bulk/destructive operations. Destructive and wide-ranging agent changes require confirmation and audit records.
- MCP is optional: tasks and inbox remain usable offline and without LLM credits. The SHIORI service must be remotely reachable for ChatGPT, and cannot read a disconnected handset's unsynced items.
- Provider tokens and webhook secrets are never exposed to ChatGPT, WebView content, logs, or public issue reports. Validate remote webhook authenticity and the authorization of any hydrated task before use.
- ClickUp Serviteur remains independent: SHIORI does not proxy through it or require that its tools be installed.

## Extension rule

A new feature should add its domain contract and application operation *before* choosing its UI or AI tool shape. Provider- or platform-specific details must stay in adapters. Prefer a small new module with a clear owner when cohesion warrants it; do not create placeholder crates or duplicate business logic just to match a theoretical diagram.

For each change, use the [foundation extension gates](../engineering/FOUNDATION_EXTENSION_GATES.md): tests for domain invariants, persistence and migration, authorization, concurrency and failure, client parity, and honest feature availability.

## Rejected alternatives

- **SHIORI as a ClickUp client only:** violates independent offline operation and makes proprietary features a dependency.
- **SHIORI MCP delegating every call to ClickUp Serviteur:** duplicates responsibilities and cannot provide SHIORI-native inbox/scheduling semantics.
- **UI or MCP handlers writing SQLite directly:** bypasses identity, validation, authorization, audit and conflict guarantees.
- **Full-object last-write-wins synchronization:** loses concurrent edits and may resurrect deleted records.
- **Automatic ClickUp task creation on inbox capture:** conflates capture with explicit task management and can cause duplicate or unwanted provider writes.

## Follow-up and evidence threshold

1. Implement a pure inbox state model and deterministic, idempotent transitions with acceptance tests.
2. Introduce minimal typed repository/application interfaces where needed without breaking existing CLI and Android offline operations.
3. Persist inbox items transactionally through versioned SQLite migrations with real backup/restore tests.
4. Expose local inbox UI and queries, then authenticated REST/MCP tools with isolated scope tests.
5. Prove M4 sync resilience before enabling provider writes. Pilot ClickUp in read-only mode with explicit origin labels.
6. Update this ADR if observed constraints change; do not describe these contracts as implemented until they are verified.
