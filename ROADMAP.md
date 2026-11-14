# SHIORI / 栞 — Product Roadmap

> **Status:** Living proposal · **Established:** 2026-11-10 · **Repository:** `cryogenized-spec/SHIORI-`
>
> SHIORI is an independent, local-first task organizer with optional self-hosted synchronization and a first-class Model Context Protocol (MCP) interface. It belongs aesthetically to the ELF//SHELL universe, but must be useful without that context, without AI, and without an online account.
>
> **This roadmap is not a claim that these features already exist, nor a commitment to fixed release dates.** Scope and acceptance criteria should be refined during M0 before locking the v1.0 release plan.

## 1. Product principles

1. **Users own their tasks.** Portable exports and backups; no lock-in to an app, AI service, or host.
2. **Fully useful without AI.** Never require Gemini, ChatGPT, Claude, an API key, or inference credits for ordinary task management.
3. **Local-first.** Core capture, editing, search, schedules, and reminders must remain useful offline.
4. **Replaceable infrastructure.** Cloudflare is an optional deployment target; an independently runnable service and backup/restore path are requirements.
5. **MCP is a capability interface, not the database.** REST and MCP call the same domain services and permission checks; native apps need not use MCP internally.
6. **Fast by design.** Assigned-to-me and actionable views should open from local indexes without a full remote workspace scan.
7. **Minimalist, progressively disclosed UX.** The basic app stays simple; complex views, rules, and integrations are optional.
8. **Community-first.** No artificial premium restrictions on core features. AGPLv3 is the *proposed* licence, pending compatibility and legal review. Copyleft does not prohibit commercial activity.
9. **Independent product.** Do not merge SHIORI with the CiRYVA Android assistant or the ELF//SHELL Firefox project. Integrations may be added later.

## 2. Confirmed user-driven requirements

The following are the first requirements confirmed from real use of task managers such as ClickUp. Their identifiers should remain stable.

| ID | Requirement | Expected behaviour | Priority |
| --- | --- | --- | --- |
| SH-001 | **Instant “Assigned to Me” / attention panel** | Fast dropdown/drawer/shortcut showing all current-user assignments across accessible projects; expose priority, dates, project, blockers, dependencies, and actionable vs. waiting state. Provide a useful cached/offline view and its freshness indicator. | P0 |
| SH-002 | **Fast automatic time blocking** | Respect per-user working hours, breaks, existing calendar commitments, time zones, task durations, priorities, dependencies, and deadlines. Allow separate work/personal calendars, preview changes, and flag work that cannot fit. Deterministic local scheduling first; AI optional. | P0 |
| SH-003 | **Flexible views, saved filters, and FIFO** | Sort by created date, planned start, actual start, due date, priority, age, assignee, and dependency state; combine filters and save views. FIFO means *oldest eligible task first* and its sort basis must be explicit. | P0 |
| SH-004 | **Android OCR capture** | Capture camera image or document, perform on-device OCR where feasible, review text, and save as task, memo, inbox item, or follow-up. Preserve image/source and require review before creating or changing tasks. | P1 |
| SH-005 | **Universal capture inbox** | Independently capture and triage notes, ideas, images, OCR output and connected-source events as durable inbox items. Convert to a task, memo or follow-up only after an explicit action; support archive and source provenance. Expose inbox operations through the same application services used by SHIORI MCP and native clients. | P0 |

## Design memo — 2026-11-14: SHIORI inbox, MCP and ClickUp interoperation

**Decision and intent (confirmed by user):** SHIORI owns a first-class universal inbox independent of any third-party provider. ChatGPT connects to SHIORI's own MCP and can inspect, triage, prepare conversions, link records and request scheduling through SHIORI domain/application services. This is **not** a replacement, duplicate or proxy for ClickUp Serviteur; Serviteur remains a separate AI-to-ClickUp integration.

- **Three distinct roles:** SHIORI is the local-first task/inbox system of record for SHIORI-native items; the SHIORI MCP is an authenticated AI adapter to those services; the ClickUp REST connector is an optional external task provider adapter. UI, REST, CLI and MCP share authorization and application commands, not direct database writes.
- **No assumed ClickUp Inbox access:** SHIORI's inbox is not ClickUp's proprietary notification Inbox. No claim of parity or unrestricted access to endpoints that the public ClickUp API does not expose. Import only supported ClickUp objects/events with explicit provenance and permission checks.
- **Identity and linking:** use stable SHIORI IDs plus scoped external-provider IDs (provider, account/workspace, resource type, remote ID). Never deduplicate by title or overwrite local items solely because a matching remote task exists; an inbox item is not implicitly a task.
- **Offline-safe sync:** local capture/triage must work without Internet, AI or Cloudflare. Remote state carries freshness metadata; writes are queued, idempotent and guarded against conflicts, duplicate retries, out-of-order webhooks and deleted record resurrection. Keep unsupported/mapped fields and any write failures visible to the user.
- **Safe AI operations:** explicit typed inbox MCP operations (list/get/capture/triage/convert/archive/link) and scheduling previews; permission checks at the service boundary; agent bulk writes, deletion and rescheduling require user-controlled review and appropriate confirmation. No covert ClickUp writes merely because an inbox item was captured.
- **Provider strategy:** the first preferred integration is ClickUp REST (read-only assigned tasks and selectable Lists first; bidirectional edits only after sync/conflict tests). Design the connector contract so Google Tasks and other sources can be added without changing SHIORI's core domain.

**Implementation sequencing:** preserve the existing M2/M3 offline foundation. Specify inbox entities, service ports, provenance and migration contracts early; implement local inbox independently; build reliable M4 sync and authenticated M5 MCP before permitting external provider writes in M6. These are design commitments, **not claims of implemented sync or Inbox access**. See [ADR 0002](docs/adr/0002-application-ports-and-provider-boundaries.md) and [foundation gates](docs/engineering/FOUNDATION_EXTENSION_GATES.md).

## 3. Feature catalogue for scope evaluation

**Foundational (P0):** tasks, notes/descriptions, projects, subtasks, tags, statuses, priorities, assignments, distinct created/planned-start/actual-start/due/completion timestamps, searchable indexes, task history, recurrence, dependencies, blocker reasons, a distinct durable inbox with capture/triage/archive, quick capture, saved filters, reliable local notifications, data export/import, secure backups, accessibility, keyboard navigation, and user-configurable work schedules.

**Advanced productivity (P1):** Kanban, calendar, table, timeline and Gantt-like views; robust recurrence exceptions and templates; weekly planner; time estimates vs. actuals; transparent rescheduling suggestions; distraction-light focus mode; OCR capture; task provenance and source links; flexible widgets and shortcuts; dependency-aware prioritization.

**Interoperability (P1):** documented REST API, explicit typed MCP tools, optional MCP Apps compact task views, CalDAV/VTODO interoperability adapter, webhook subscriptions, and portable deployment. External task-provider connectors (e.g. ClickUp, Google Tasks) come later and must preserve source IDs and conflicts rather than silently duplicate tasks.

**Exploratory (P2):** habit tracking, sophisticated rules/automation builder, user-defined workflows, workload forecasting, team dashboards, extensive integrations, community plugins, optional local or external AI-driven planning, and more specialized project-management features.

**Non-goals for the first release:** claiming access to ClickUp's native notification Inbox, mandatory embedded AI, built-in LLM inference, enterprise ERP, complex HR/payroll features, requiring Cloudflare, or assuming all MCP clients can render rich UI.

## 4. Architecture boundaries

The repository should start as a modular monorepo; names are provisional until M0 produces Architecture Decision Records (ADRs).

```text
apps/
  api/              # portable self-hosted HTTP service
  web/              # responsive web/desktop-friendly client
  android/          # independent native Android client (Kotlin/Compose candidate)
packages/
  contracts/        # typed shared schemas and compatibility rules
  core/             # task domain logic; independent of hosting and transport
  storage/          # adapters and migrations; local-first design
  sync/             # device synchronization, conflicts, deletion/tombstones
  auth/             # authentication, authorization and scoped access
  scheduling/       # deterministic scheduling and time-blocking
  query/            # assignments, dependencies, filters, indexing
  mcp/              # explicit individual MCP operations, transport adapters
  mcp-ui/           # optional, versioned compact MCP Apps resources
  integrations/     # CalDAV and third-party task-provider adapters
deploy/             # replaceable deployment targets, local/Docker first
docs/               # PRD, ADRs, feature matrix, threat model, API specs
tests/              # integration, contract, performance and migration tests
```

**Rules:**
- UI, MCP, REST, and automation must use the same domain application services; no direct database access from presentation tools.
- Querying assigned tasks must not trigger a scheduling pass.
- All remote writes enforce auth and permissions on the server; never trust a UI/AI client to enforce them.
- Dependence on infrastructure-specific services must remain behind adapters.
- Define stable IDs, schema versions, migrations, change logs, delete semantics, time zones, and recurrence semantics early.
- Do not assume SQLite and cloud database semantics are identical; use portable contracts and test supported combinations.
- Treat MCP Apps as an optional enhancement. Non-UI MCP clients still receive structured or readable results.
- For a fast task panel, show cached results with an explicit sync/freshness state; never silently claim fresh data.
- Use maintained supported runtimes and dependencies at implementation time; reproducible lockfiles, audits and updates.

## 5. Milestones and exit criteria

### M0 — Research, requirements and project foundation
**Deliver:** compare existing open-source task managers and commercial premium capabilities; finalize the requirements catalogue and user journeys; product requirements document (PRD); fork-vs-new-core decision; open-source licence and dependency compatibility review; ADRs for domain model, offline sync, client architecture, hosting, MCP, and permissions; initial repo structure and CI; documented performance targets and supported platforms.

**Exit:** scope for v0.1 and v1.0 is explicit; each P0 feature has acceptance tests; legal/licence decisions and a reproducible development environment are recorded.

### M1 — Local task-domain foundation
**Deliver:** task/project models, validation, creation/edit/completion, subtasks, multiple date concepts, priorities/statuses, dependency graph, recurrence model, change history, local persistence, import/export basics, and query/index APIs.

**Exit:** create, edit, search, complete, restore, and filter tasks offline; cyclic dependencies are rejected; recurrence and time-zone edge cases have automated tests.

### M2 — Daily-use app and instant attention views
**Deliver:** usable responsive web UI; native Android shell and local task operations; SH-001 fast “Assigned to Me” drawer; actionable/blocked states; SH-003 saved filters and FIFO views; local SH-005 inbox capture/triage/archive; notifications and quick capture.

**Exit:** users can manage daily tasks without a server; attention panel opens from local data quickly under a defined benchmark, even with a realistic large fixture; filters behave consistently across clients.

### M3 — Scheduling and automatic time blocking
**Deliver:** SH-002 local deterministic scheduler; work/personal availability profiles, breaks, calendar busy-time import, durations, priorities, dependency constraints, schedule previews, conflict reporting, and undo.

**Exit:** generated blocks respect availability and dependency order; unschedulable work is reported rather than dropped; user remains in control of applying changes.

### M4 — Optional sync, accounts and portable hosting
**Deliver:** independent server, authentication and permission model, sync protocol, conflict resolution, tombstones, secure backup/restore, multiple-device testing, and Docker/local deployment. Additional cloud targets remain adapters, not prerequisites.

**Exit:** offline edits converge safely after reconnect; conflicts and deletes are not lost; a documented export/restore migration succeeds between two independently operated environments.

### M5 — MCP interoperability and compact UI
**Deliver:** typed, separately named MCP tools for tasks, inbox capture/triage/conversion/archive, projects, assignments, filters, dependencies and schedules; scoped tokens/permissions; error contracts; optional lightweight versioned MCP Apps views.

**Exit:** supported MCP clients can read/manage permitted tasks; destructive operations have appropriate safeguards; clients without UI support still work; no model API key required by SHIORI.

### M6 — OCR capture, CalDAV and integrations
**Deliver:** SH-004 on-device Android OCR capture-and-review flow; optional universal inbox if approved; CalDAV/VTODO adapter with round-trip tests; source provenance; ClickUp as the preferred first external task-provider connector, subject to provider/API and sync acceptance gates.

**Exit:** OCR produces editable text and a traceable source attachment; task/calendar interoperability documents unsupported fields and preserves user data rather than silently dropping it.

### M7 — Advanced productivity and release hardening
**Deliver:** additional views, templates, useful analytics, focus/time utilities, performance profiling, localization, accessibility, security audit, contributor docs, packaging, reproducible releases, and migration guidance.

**Exit:** stable v1.0 release candidate passes functional, accessibility, security, backup/restore, compatibility, and performance acceptance suites.

### M8+ — Extensibility and collaboration
**Candidates:** rule/automation builder, plugins, richer multiuser collaboration and workload views, wider provider connectors, sophisticated forecasting, and community-driven improvements.

**Gate:** accept only after user research, security analysis, maintenance assessment and updated ADRs.

## 6. Release strategy

- **v0.1 (internal alpha):** M1 + a minimal usable subset of M2. Validate domain model and everyday workflows.
- **v0.x previews:** prove scheduling, sync and MCP separately through milestone gates; do not claim a feature is production-ready merely because an API endpoint exists.
- **v1.0:** stable P0 experience, portable synchronization, MCP support, accessible UI, tested backup/restore; OCR and CalDAV should be included if they meet M6 gates, otherwise move them into a published near-term post-v1 plan.
- **After v1.0:** expand P1/P2 on evidence, not feature-count targets.

**Scope discipline:** release labels and milestone boundaries can move after M0. Do not promise dates before complexity and maintenance burden are measured.

## 7. Initial technical quality gates

- **Performance:** benchmark instant assigned-to-me retrieval, complex saved filters, scheduling runtime, Android startup, and offline searches using realistically sized data. Choose numeric SLOs in M0 rather than inventing them now.
- **Offline correctness:** test edits on two devices, out-of-order updates, deletions, duplicate retries, recurrence transitions, and time-zone changes.
- **Security:** least-privilege access, auditability of agent writes, scoped tokens, secure secret storage, authorization at service boundaries, and no silent external transmission of OCR material.
- **Interoperability:** explicit contracts and protocol-conformance tests; graceful degradation when host applications do not support MCP UI, and field-level loss reporting for CalDAV/third-party connectors.
- **Portability:** run core and service without mandatory proprietary cloud components; routinely test backup/export/import and provider migration.
- **Maintainability:** bounded module dependencies, static analysis, tests at domain boundaries, compatible dependencies, contributor documentation, and reviewable incremental PRs.

## 8. Open decisions — complete in M0

1. **Repo identity:** retain `SHIORI-` or rename to a clean slug; public application name remains **SHIORI / 栞**.
2. **Licence:** evaluate AGPLv3 against third-party dependencies, Android distribution obligations, and contributor expectations; do not copy GPL/AGPL modules into incompatible code.
3. **Task model:** single-user-first with team-ready permissions vs. a full multi-user model from day one.
4. **Synchronization:** operation-log vs. other change-tracking approaches; conflict-resolution contract; local storage and server DB adapters.
5. **Scheduling:** precise policy for ranking, task splitting, manually pinned time blocks, recurring schedules, travel/break constraints, and overflow.
6. **MCP tool set:** separate explicit operations, auth scopes, confirmation requirements, write audit trail, and UI resource versions.
7. **OCR:** engine choices, offline-language support, image retention, confidence indicators, and user verification.
8. **CalDAV:** required VTODO fields, compatibility matrix, recurrence behaviour, mapping losses, and treatment of newer extensions.
9. **Release scope:** whether M6 OCR and CalDAV are firm v1.0 blockers or early post-v1 additions, based on measured effort.
10. **Governance:** project conduct, contribution process, sustainable maintenance, trademarks, and commitment to freely available core functionality.

## 9. Near-term next actions

1. Finish the competitor / paywall / open-source capability matrix; include Vikunja, tududi, Super Productivity, Tasks.org, and further references.
2. Turn SH-001–SH-004 into detailed user stories and reproducible acceptance tests.
3. Write an architecture decision comparing selective reuse versus a new core, including licensing and dependency risk.
4. Specify the canonical task schema, recurrence semantics, dependencies, indexing and offline conflict model.
5. Create the minimal project skeleton, CI and a local-only task CRUD prototype **after** the M0 decisions.
6. Record additional requirements as they arise; SH-005 remains a suggestion until approved.

---

*Guiding promise: SHIORI should help people finish their work and leave the app—not hold their attention, data, or choice of AI provider hostage.*
