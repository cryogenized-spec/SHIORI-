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
| SH-006 | **Infinite Spatial Workspace** | Free-running, pannable, zoomable dotted-grid canvas; first-class artefacts and typed relations; semantic zoom into glyph/colour-coded clusters and blocker markers; deterministic, bounded contextual retrieval from an indexed permanent library. Store spatial layout separately from graph meaning. | P1 |
| SH-007 | **Expressive Agent Interface (EAI)** | Schema-driven interactive explanations and manipulable 2D/polygonal scenes, with optional layered/3D views, provenance, AI-proposed scene changes and MCP Apps transport. Examples include an explorable locust lifecycle and a task-blocker explanation. Text-only fallback required. | P1 |

## Design memo — 2026-11-14: SHIORI inbox, MCP and ClickUp interoperation

**Decision and intent (confirmed by user):** SHIORI owns a first-class universal inbox independent of any third-party provider. ChatGPT connects to SHIORI's own MCP and can inspect, triage, prepare conversions, link records and request scheduling through SHIORI domain/application services. This is **not** a replacement, duplicate or proxy for ClickUp Serviteur; Serviteur remains a separate AI-to-ClickUp integration.

- **Three distinct roles:** SHIORI is the local-first task/inbox system of record for SHIORI-native items; the SHIORI MCP is an authenticated AI adapter to those services; the ClickUp REST connector is an optional external task provider adapter. UI, REST, CLI and MCP share authorization and application commands, not direct database writes.
- **No assumed ClickUp Inbox access:** SHIORI's inbox is not ClickUp's proprietary notification Inbox. No claim of parity or unrestricted access to endpoints that the public ClickUp API does not expose. Import only supported ClickUp objects/events with explicit provenance and permission checks.
- **Identity and linking:** use stable SHIORI IDs plus scoped external-provider IDs (provider, account/workspace, resource type, remote ID). Never deduplicate by title or overwrite local items solely because a matching remote task exists; an inbox item is not implicitly a task.
- **Offline-safe sync:** local capture/triage must work without Internet, AI or Cloudflare. Remote state carries freshness metadata; writes are queued, idempotent and guarded against conflicts, duplicate retries, out-of-order webhooks and deleted record resurrection. Keep unsupported/mapped fields and any write failures visible to the user.
- **Safe AI operations:** explicit typed inbox MCP operations (list/get/capture/triage/convert/archive/link) and scheduling previews; permission checks at the service boundary; agent bulk writes, deletion and rescheduling require user-controlled review and appropriate confirmation. No covert ClickUp writes merely because an inbox item was captured.
- **Provider strategy:** the first preferred integration is ClickUp REST (read-only assigned tasks and selectable Lists first; bidirectional edits only after sync/conflict tests). Design the connector contract so Google Tasks and other sources can be added without changing SHIORI's core domain.

**Implementation sequencing:** preserve the existing M2/M3 offline foundation. Specify inbox entities, service ports, provenance and migration contracts early; implement local inbox independently; build reliable M4 sync and authenticated M5 MCP before permitting external provider writes in M6. These are design commitments, **not claims of implemented sync or Inbox access**. See [ADR 0002](docs/adr/0002-application-ports-and-provider-boundaries.md) and [foundation gates](docs/engineering/FOUNDATION_EXTENSION_GATES.md).


## Design memo — 2026-11-14: Bipartite spatial + expressive implementation (SH-006 / SH-007)

**Confirmed product direction:** Replace obligatory vertical/horizontal list navigation with a bird's-eye, freely navigable view of interconnected work. The agent must be able to *communicate with objects* rather than only text, links or Mermaid-like static chains. These are **two cooperating implementation tracks**, not one coupled monolith; both reuse SHIORI's canonical artefact/relationship services and access controls. They are goals, not shipped features.

### Part I — SH-006: Infinite Spatial Workspace

**User experience.** A genuinely unbounded 2D workspace (not infinite network loading and not simply a background CSS pattern) with a subtle dotted square grid, pan/zoom, reliable viewport persistence, keyboard navigation, minimap/overview, zoom-to-fit and selection/focus. List, kanban, timeline and graph views remain alternate projections of the **same** data, not separate stores. Navigation must favour an immediately legible bird's-eye understanding rather than scrolling through rows, columns or comments.

**Artefacts-as-first-class:** a stable, typed, provenance-carrying identity layer for task, inbox item, note/memo, project, milestone, reference/document and linked attachment; more types via explicitly versioned extensions. Do **not** flatten currently distinct Task and InboxItem aggregates into a lossy generic table. Introduce an `ArtifactRef`/registry or read projection over existing domain records, with typed metadata and permission checks; preserve original source, remote IDs, revisions and lifecycle rules.

**Typed relationships:** distinct, directed `blocks / depends_on` execution links, `contains / part_of` hierarchy, `references / related_to` knowledge links, and `captured_from / converted_to` provenance links. Reverse traversal/backlinks are queryable. Hard dependency links enforce cycle checks and scheduling semantics; semantic links may form cycles. Preserve relationship provenance and revision history. Task links and comments/attachments can be promoted into navigable references without inventing inaccessible ClickUp Inbox events.

**Semantic zoom:** zoom is *level-of-detail*, not merely card scaling. At close range show task/artefact details and attachments as small offshoots; at middle range show readable clusters and dependency branches; at far range aggregate to compact map-marker-like glyphs that show meaningful blocker/actionability counts and critical paths. Prefer **red for real blockers/critical dependencies**, not for every node; add other restrained, user-configurable legend categories and **glyphs/shapes alongside colour** for colour-vision accessibility. Keep summary counts, legend, selection identity and drill-down consistent when changing zoom; avoid rendering all edges at once.

**Deterministic retrieval librarians:** lightweight workers/indexes for document text/OCR extraction, metadata and attachment indexing, graph traversal and backlink collection, de-duplication, freshness checks, and query/ranking. A context planner selects bounded neighbourhoods and source snippets according to relevance, user scope, recency, relationship depth and an explicit token/byte budget. Return `source IDs + confidence/uncertainty + freshness + redacted snippets`, not an unbounded dump of the whole library. Workers are repeatable, cancellable, permission-aware, and can run without an LLM; model reasoning is reserved for ambiguous synthesis/planning. Never let retrieved text silently become instructions.

**Persistence and rendering boundary:** canonical records + typed edges live in the SHIORI domain/application/storage path; canvas positions, viewport, collapsed groups and visual styles are separate versioned *view state*. Moving a node or auto-layout **must not mutate** its task dependencies. Spatial clustering/virtualisation, viewport culling and incremental graph queries must stay usable with realistic hundreds/thousands of items and preserve an accessible non-canvas view. Start with indexed SQLite and evaluate alternate stores/renderers only on measured need.

**Part I incremental proof:** (a) define artefact-reference/edge/scene-view contracts and invariants; (b) implement local persistent cross-artefact links + backlinks and bounded graph retrieval; (c) implement actual pan/zoom dotted infinite canvas, typed nodes and editable links; (d) add semantic-zoom glyph/colour legend, clusters and offshoots; (e) integrate secure context librarians and benchmark large fixtures. A successful demo shows an entire repair workspace zoomed out to blocker markers, then drilled into a repair, quotation, attachment and actionable fork **without scrolling lists or altering underlying task meaning**.

### Part II — SH-007: Expressive Agent Interface (EAI)

**Purpose:** The agent assembles and operates an **interactive explanation scene**, instead of merely replying with prose, task links or flat Mermaid-style diagrams. It can focus, highlight, expand, collapse, annotate, compare, animate and navigate typed objects; users can point/select and ask follow-up questions about *that object*. Explanations are structured scenes over retrieved evidence, **not arbitrary agent-generated executable UI code**.

**Scene language:** define a small versioned, engine-neutral `EaiScene` contract with scene/node IDs, semantic object types, polygon/path/geometry primitives, layers, connectors and their meanings, camera/viewport, legends, labels/accessibility descriptions, bounded interaction events, time or animation tracks, references/provenance, and explicit distinctions among **observed facts, inferred relationships, hypotheses and illustrative graphics**. Support 2D/SVG/canvas first; add layered/polygonal 2.5D or optional WebGL/3D only where it genuinely clarifies the subject. Reuse the Part I renderer/selection and graph-query capabilities without coupling EAI scenes to permanent task mutations.

**Interaction boundary:** agent issues validated commands (`create_scene`, `add_objects`, `link_objects`, `focus`, `highlight`, `set_view`, `animate`, `propose_changes`—conceptual names only). Rendering events and user selection are returned as bounded, scoped context. A visual explanation is read-only by default; saving it as an artefact or proposing changes to real tasks/edges is a separate permissioned action with preview/diff, revision checks, audit, undo/recovery and user approval for material edits. Never execute arbitrary script from prompts, documents or tool output.

**Concrete exemplar:** an agent-produced *locust lifecycle* scene that displays polygonal/illustrated egg → nymphal hopper → adult forms, optional environmental and population conditions, time progression and branching causal links; zoom/selection reveal sourced explanations and uncertainty. This is an **educational depiction**, not a validated biological simulation. A second exemplar must use actual SHIORI artefacts: a repair's blocker chain, linked supplier quote/attachment, and downstream actionable forks, with source drill-down and explicit proposed restructuring rather than hidden writes.

**Delivery:** the same scene contract can render inside SHIORI desktop/Android and, where negotiated and supported, an MCP Apps (`ui://`) resource in an external AI host. MCP Apps already standardises transport for interactive interfaces; EAI should **reuse** it rather than create a competing AI-to-UI protocol. Provide plain text/structured-data descriptions for clients without MCP Apps. Context is retrieved on demand and bounded; no mandatory AI provider or online service is needed for basic local graph exploration.

**Part II incremental proof:** (a) scene schema, validator and deterministic renderer with no model dependency; (b) locust example scene authored from trusted fixture data; (c) user selection and agent-controlled navigation/animation with safe events; (d) SHIORI retrieval-to-scene pipeline with citations and bounded context; (e) MCP Apps adapter and read-only explanation; (f) reviewed graph restructuring previews and safety tests. Do not claim EAI works merely because an MCP App iframe displays a static chart.

### Independence, licensing and existing equivalents

- **Existing equivalents / interoperability:** Official [MCP Apps](https://github.com/modelcontextprotocol/ext-apps/blob/main/specification/2026-01-26/apps.mdx) supplies interactive MCP UI transport, **not** our spatial graph and context-aware polygonal scene composition. [React Flow / xyflow](https://github.com/xyflow/xyflow) (MIT), [Cytoscape.js](https://js.cytoscape.org/) (MIT) and [Excalidraw](https://github.com/excalidraw/excalidraw) (MIT) are candidate rendering/editing foundations, not a complete EAI. [JSON Canvas](https://obsidian.md/blog/json-canvas/) (open MIT spec) is a candidate interchange format. Evaluate fit, accessibility and large-graph performance rather than adopting a framework by default. [tldraw's SDK](https://tldraw.dev/sdk-features/license-key) needs a production licence key, so do not assume it is an MIT/zero-cost production dependency.
- **EAI licensing proposal, not an adopted licence:** Prefer a *standalone, generic and portable* EAI scene-schema + renderer package that **could** be published under MIT, subject to code provenance, permission from contributors, dependency audit, patent/trademark considerations and the existing SHIORI AGPLv3-proposed policy. If SHIORI itself is eventually AGPL, an independently authored MIT package can be depended on by SHIORI, but **relicensing existing AGPL contributions MIT is not automatic**. Do not add a repository-wide MIT `LICENSE` or promise permissive licensing until legal and contributor decisions are resolved.
- **Single source of truth:** Part I's artefact/edge graph is persisted user data; Part II's `EaiScene` is a derived, editable visual explanation *view*, persisted only by explicit save. The interface must never mistake a simulated shape or inferred dependency for a verified task record.

**Bipartite exit criterion:** The same linked SHIORI repair artefacts can be navigated at bird's-eye-to-detail scale, retrieved under a bounded evidence budget and rendered as a traceable interactive EAI explanation; the same EAI engine can explain a standalone scientific example. No unapproved graph changes, data leakage or mandatory proprietary service.

**Scheduling:** deliver Part I local contracts and a UX proof as extensions of M1/M2 (without destabilising SH-005). Fold graph indexing/retrieval into M4/M5 readiness. Prototype Part II's renderer independently before MCP connectivity, then add MCP Apps transport in/after M5. Treat their production hardening as two explicitly gated M7 workstreams, not blockers for the current offline-alpha milestone; defer v1.0 inclusion decisions until performance, reliability and licensing are demonstrated.

## 3. Feature catalogue for scope evaluation

**Foundational (P0):** tasks, notes/descriptions, projects, subtasks, tags, statuses, priorities, assignments, distinct created/planned-start/actual-start/due/completion timestamps, searchable indexes, task history, recurrence, dependencies, blocker reasons, a distinct durable inbox with capture/triage/archive, quick capture, saved filters, reliable local notifications, data export/import, secure backups, accessibility, keyboard navigation, and user-configurable work schedules.

**Advanced productivity (P1):** SH-006 spatial workspace, semantic zoom, typed artefact relations/backlinks and bounded context retrieval; SH-007 expressive scene engine and interactive explanations; Kanban, calendar, table, timeline and Gantt-like views; robust recurrence exceptions and templates; weekly planner; time estimates vs. actuals; transparent rescheduling suggestions; distraction-light focus mode; OCR capture; task provenance and source links; flexible widgets and shortcuts; dependency-aware prioritization.

**Interoperability (P1):** versioned scene contracts and JSON Canvas export/import where practical, documented REST API, explicit typed MCP tools, optional MCP Apps compact task views, CalDAV/VTODO interoperability adapter, webhook subscriptions, and portable deployment. External task-provider connectors (e.g. ClickUp, Google Tasks) come later and must preserve source IDs and conflicts rather than silently duplicate tasks.

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
  graph/            # typed artefact refs, relationship queries and graph projections (proposed)
  spatial/          # view-only canvas state and semantic zoom rendering (proposed)
  eai/              # portable typed EAI scene contract/renderers, licence pending (proposed)
  retrieval/        # deterministic, bounded, permissioned context retrieval (proposed)
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
**Deliver:** usable responsive web UI; native Android shell and local task operations; optional SH-006 local spatial canvas proof without changing canonical task data; SH-001 fast “Assigned to Me” drawer; actionable/blocked states; SH-003 saved filters and FIFO views; local SH-005 inbox capture/triage/archive; notifications and quick capture.

**Exit:** users can manage daily tasks without a server; attention panel opens from local data quickly under a defined benchmark, even with a realistic large fixture; filters behave consistently across clients.

### M3 — Scheduling and automatic time blocking
**Deliver:** SH-002 local deterministic scheduler; work/personal availability profiles, breaks, calendar busy-time import, durations, priorities, dependency constraints, schedule previews, conflict reporting, and undo.

**Exit:** generated blocks respect availability and dependency order; unschedulable work is reported rather than dropped; user remains in control of applying changes.

### M4 — Optional sync, accounts and portable hosting
**Deliver:** independent server, authentication and permission model, sync protocol, conflict resolution, tombstones, secure backup/restore, multiple-device testing, and Docker/local deployment. Additional cloud targets remain adapters, not prerequisites.

**Exit:** offline edits converge safely after reconnect; conflicts and deletes are not lost; a documented export/restore migration succeeds between two independently operated environments.

### M5 — MCP interoperability and compact UI
**Deliver:** typed, separately named MCP tools for tasks, inbox capture/triage/conversion/archive, projects, assignments, filters, dependencies and schedules, plus bounded artefact-graph queries and optional EAI scene retrieval; scoped tokens/permissions; error contracts; optional lightweight versioned MCP Apps views.

**Exit:** supported MCP clients can read/manage permitted tasks; destructive operations have appropriate safeguards; clients without UI support still work; no model API key required by SHIORI.

### M6 — OCR capture, CalDAV and integrations
**Deliver:** SH-004 on-device Android OCR capture-and-review flow; optional universal inbox if approved; CalDAV/VTODO adapter with round-trip tests; source provenance; ClickUp as the preferred first external task-provider connector, subject to provider/API and sync acceptance gates.

**Exit:** OCR produces editable text and a traceable source attachment; task/calendar interoperability documents unsupported fields and preserves user data rather than silently dropping it.

### M7 — Advanced productivity and release hardening (two spatial/EAI tracks)
**Workstream M7-A / SH-006:** complete the infinite workspace, typed artefact relations, backlink/navigation indexes, legend+glyph semantic zoom, attachment/actionable offshoots and deterministic contextual librarians. Measure large-fixture render latency, graph query cost and offline interaction. Keep view-state separate from domain edges.

**Workstream M7-B / SH-007:** complete a portable expressive scene validator/renderer, provenance-carrying polygonal lifecycle example, SHIORI repair-graph explanation, agent-to-scene operations and MCP Apps adapter with text fallback. Agent-suggested restructuring is preview/diff-first and cannot write canonical data without authorization and review.

**Other deliverables:** additional views, templates, useful analytics, focus/time utilities, performance profiling, localization, accessibility, security audit, contributor docs, packaging, reproducible releases, and migration guidance.

**Exit:** each workstream has separate acceptance criteria in the design memo. SHIORI v1.0 release candidacy still requires functional, accessibility, security, backup/restore, compatibility and performance tests; shipping both M7 workstreams in v1.0 is an **open release-scope decision**, not an implicit promise.

### M8+ — Extensibility and collaboration
**Candidates:** rule/automation builder, plugins, richer multiuser collaboration and workload views, wider provider connectors, sophisticated forecasting, and community-driven improvements.

**Gate:** accept only after user research, security analysis, maintenance assessment and updated ADRs.

## 6. Release strategy

- **v0.1 (internal alpha):** M1 + a minimal usable subset of M2. Validate domain model and everyday workflows.
- **v0.x previews:** prove scheduling, sync and MCP separately through milestone gates; do not claim a feature is production-ready merely because an API endpoint exists.
- **v1.0:** stable P0 experience, portable synchronization, MCP support, accessible UI, tested backup/restore; OCR, CalDAV and the SH-006/SH-007 advanced workstreams are scoped to the release only when their separate acceptance gates pass, otherwise assigned to published post-v1 milestones.
- **After v1.0:** expand P1/P2 on evidence, not feature-count targets.

**Scope discipline:** release labels and milestone boundaries can move after M0. Do not promise dates before complexity and maintenance burden are measured.

## 7. Initial technical quality gates

- **Performance:** benchmark instant assigned-to-me retrieval, complex saved filters, scheduling runtime, Android startup, and offline searches using realistically sized data. Choose numeric SLOs in M0 rather than inventing them now.
- **Offline correctness:** test edits on two devices, out-of-order updates, deletions, duplicate retries, recurrence transitions, and time-zone changes.
- **Security:** least-privilege access, auditability of agent writes, scoped tokens, secure secret storage, authorization at service boundaries, and no silent external transmission of OCR material.
- **Interoperability:** explicit contracts and protocol-conformance tests; graceful degradation when host applications do not support MCP UI, and field-level loss reporting for CalDAV/third-party connectors.
- **Portability:** run core and service without mandatory proprietary cloud components; routinely test backup/export/import and provider migration.
- **Maintainability:** bounded module dependencies, static analysis, tests at domain boundaries, compatible dependencies, contributor documentation, and reviewable incremental PRs.
- **Spatial and expressive correctness:** guarantee that canvas rearrangement cannot mutate dependencies; test zoom/glyph legend accessibility, large graph culling, link-cycle rules, citation/provenance fidelity, context budgets, scene-schema validation, agent-proposed diff review, and plain-text fallback.

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
11. **SH-006 design:** artefact registry vs. a generic aggregate, graph index/query contracts, spatial rendering framework, zoom thresholds and glyph/colour accessibility.
12. **SH-007 licence and engine:** separate MIT-licensed EAI package vs. SHIORI AGPL-proposed modules, contributor rights, candidate renderer dependency audit, scene-schema interoperability and MCP Apps compatibility.
13. **Release scope:** whether advanced SH-006/SH-007 features ship before v1.0 or in staged post-v1 releases based on measured quality gates.

## 9. Near-term next actions

1. Finish the competitor / paywall / open-source capability matrix; include Vikunja, tududi, Super Productivity, Tasks.org, and further references.
2. Turn SH-001–SH-007 into detailed user stories and reproducible acceptance tests; preserve the already confirmed SH-005 inbox requirement.
3. Write an architecture decision comparing selective reuse versus a new core, including licensing and dependency risk.
4. Specify the canonical task schema, recurrence semantics, dependencies, indexing and offline conflict model.
5. Create the minimal project skeleton, CI and a local-only task CRUD prototype **after** the M0 decisions.
6. Prototype SH-006 on existing demo or fixture data with read-only graph views, then separately validate an EAI scene-schema/locust explanation proof (SH-007); neither is a replacement for unfinished offline/SQLite/sync gates.

---

*Guiding promise: SHIORI should help people finish their work and leave the app—not hold their attention, data, or choice of AI provider hostage.*
