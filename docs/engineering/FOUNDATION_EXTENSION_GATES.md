# SHIORI foundation and feature-extension gates

Status: **Architecture acceptance checklist; new capabilities must pass their applicable gates** (2026-11-14)

Related: [ROADMAP](../../ROADMAP.md), [ADR 0001](../adr/0001-rust-core-sqlite.md), [ADR 0002](../adr/0002-application-ports-and-provider-boundaries.md).

This is a guardrail for building SHIORI feature by feature, not a claim that all gates already pass. Existing prototypes may intentionally be incomplete; mark that explicitly rather than rewriting working modules, hiding risk or claiming production readiness.

## Stable responsibilities

| Concern | Single source of rules | Allowed adapters | Must not happen |
| --- | --- | --- | --- |
| Task/inbox identity and state transitions | Pure Rust domain types | CLI, Android, web, MCP, REST | Duplication of state machines in JavaScript/Kotlin/MCP |
| Authorized commands and queries | Shared application services | All front ends and agents | MCP/UI direct SQL writes or missing scope checks |
| Local durability, migrations, indexes | SQLite repository implementation | Application service via ports | Full live database file copies, lossy migrations |
| Calendar planning | Deterministic scheduler | Previews and explicit apply operations | Scheduling triggered just by viewing a task |
| Device synchronization | Versioned change contract | Client/server transports | Unreviewed last-write-wins or tombstone loss |
| ClickUp, later Google Tasks | Source-specific provider adapter | Sync engine/provider ports | Provider records as core types or mandatory login |

## Pre-implementation questions for every feature

Document the answered questions in the PR description; a brief answer is enough.

1. **User story:** What explicit action and observable outcome does this support? Does it have a stable roadmap requirement ID?
2. **Ownership:** Is this an inbox item, a task, a memo, a schedule proposal, or an external-provider record? What is the canonical owner/store?
3. **Contract:** Which commands/queries/events are new? What input validation, revision checks, errors, identity scopes and invariants apply?
4. **Compatibility:** Does this change persisted schema, APIs, tools or imports? How are old devices/files/exports kept readable?
5. **Failure:** What happens offline, on timeout, stale revision, duplicate retry, partial write, cancellation, permission denial and process termination?
6. **Security:** Who can read/write it? Are imported texts, attachments and webhook payloads untrusted? Is any secret/logging boundary crossed?
7. **Performance:** Does it keep attention/inbox views indexed and fast? Does background sync avoid blocking capture?
8. **Evidence:** Which tests prove the above and which important checks remain outstanding?

## Mandatory gates by change category

**Domain change:** model tests cover valid and invalid transitions, duplicate operations, explicit date-only vs. instant semantics, stable IDs, revisions and no hidden side effects. Pure core remains free of transport and persistence dependencies.

**Storage or migration:** migration fixture from the last shipped schema; rollback/invalid-schema tests; old task IDs and tombstones retained; transactional writes; backup/restore verified using SQLite-approved backup facilities. Database version bump only when schema actually changes.

**New UI:** works on actual offline local data, including empty and large collections. Queries never trigger writes. Handle back/cancel, search and accessible controls. The client uses shared state/contract rather than a second task model. Android physical-device testing is a release gate, not implied by CI builds.

**New MCP or REST operation:** typed schema and named method; explicit read vs. write, resource scope, version precondition, pagination and structured failure. Demonstrate that unauthorized workspace IDs fail. Agent bulk/destructive changes require review/confirmation, audit and idempotency. No secrets in outputs.

**Sync/provider:** provider capabilities declared and tested; source identities include account/workspace; freshness shown; offline queue replay and recovery; duplicate and out-of-order event tests; conflicting edits preserved; deletes not resurrected; webhook signature checked; remote record re-fetched under the correct auth scope; unrecognized fields reported. A read-only connector does not silently start writing.

**Scheduling:** reproducible plan preview with work hours, breaks, time zones, dependencies and overload; no writes until explicit apply; undo or revision-aware correction and audit for applied changes.

## Proposed SH-005 first vertical slice (M2, no cloud dependency)

1. **Domain:** `InboxItem` has its own stable ID, owner, captured/updated timestamps, revision, safe content reference, source provenance, state and links. Define `Capture`, `Triage`, `Convert/Link`, `Archive` transitions; task creation is never a side effect of capture.
2. **Repository:** create a versioned SQLite schema and indexed queries for `unprocessed`, `archived`, and by-capture-date. Preserve source items when converting and ensure one conversion cannot create multiple tasks on retries.
3. **Application:** expose `capture_inbox_item`, `list_inbox`, `get_inbox_item`, `triage_inbox_item`, `convert_inbox_item`, and `archive_inbox_item` as typed operations. Implement conversion as a single atomic application transaction, not two unrelated writes.
4. **Local client:** render a native/offline inbox with capture, review, explicit conversion and archive; no live ClickUp access needed.
5. **MCP follow-on:** expose equivalent scoped methods through the eventual authenticated SHIORI MCP. Preserve original source data and clearly label the proposed-vs-applied state.
6. **ClickUp pilot follow-on:** read-only import of tasks assigned to the user, then optional selected Lists. Link by scoped remote IDs, maintain change/freshness markers, and only later open a reviewed outbound patch path.

**Done for the first slice** means steps 1–4 work offline and pass automated tests; 5–6 are *not* prerequisites to demonstrate the local inbox and must not be misreported as delivered.

## PR template: short evidence report

```text
Requirement:
Domain owner + application commands:
Schema/API/tool compatibility:
Offline and error behaviour:
Security scopes / provenance:
Tests executed and results:
Known gaps / follow-up gate:
```

## Current reality check (2026-11-14)

- Rust domain + SQLite storage, local CLI and experimental Android Rust working copy exist.
- Android's ordinary live tasks and native SQLite working copy are not yet one authoritative store.
- No production SHIORI MCP, provider sync service, universal inbox or ClickUp integration has been verified.
- This document **defines acceptance criteria**; it does not make those features operational.
