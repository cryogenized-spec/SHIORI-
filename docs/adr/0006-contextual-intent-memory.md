# ADR 0006 — Contextual intent memory and adaptive clarification

**Status:** Proposed experimental SH-MEM-002 slice. The pure Rust resolver, optional
SQLite sidecar and offline CLI are implemented on the linked PR branch. Agent
observation, semantic expansion, native UI, automatic procedure execution,
cloud synchronisation and MCP exposure are **not** implemented.

## Problem

Expressions such as "make a note of this" carry workspace- and project-specific
meaning. An assistant may interpret them literally, prompting corrective feedback.
Repeating these misunderstandings across model changes is inefficient. A model's
own conversational memory cannot be the source of operational authority.

## Decision

Use a provider-neutral **Contextual Intent Memory** (CIM) in SHIORI:

1. Store normalized expression + explicit human meaning + **registered procedure
   ID** + trusted workspace/project scope + evidence ID.
2. Treat a user's *explicit correction* as evidence of a provisional rule.
   Frustration/anger is not classified or persisted as a user trait. A model may
   propose a correction from user text, but the host must verify the original
   evidence and enforce user memory settings before recording it.
3. Reuse the just-corrected meaning **within the current turn** when enough
   information was supplied, subject to normal tool permissions and approval.
4. On later turns, unfamiliar, conflicting or insufficiently verified expressions
   cause a short, specific clarification. Two independently verified correct
   procedure outcomes graduate the exact scoped expression to low-friction
   interpretation, **not** to automatic authorisation.
5. When a correction changes an interpretation, successful-use evidence for the
   old meaning no longer counts. Revision-checked writes reject stale outcomes.
6. Project-specific interpretations override workspace-wide ones; never transfer
   rules between workspaces by default. The application determines scope from
   authenticated identity and active context, not from arbitrary model-supplied IDs.
7. Exact expression matching ships first. Elara's evidence-rich retrieval,
   aliases and semantic expansion may be added later, but expansion can only
   suggest interpretations. It cannot bypass ambiguity handling or authorization.

## First working slice

- `shiori_core::contextual_intent`: validated correction, portable rule,
  deterministic phrase normalization and interpretation decisions.
- `shiori_storage::IntentStore`: versioned `tasks.intent.sqlite3` SQLite
  sidecar, atomic correction/success writes, provenance IDs and replay checks.
  No migration of canonical task schema v3.
- `shiori-cli`: `intent-correct`, `intent-resolve`, `intent-success`.
  This is a **manual test surface**, not an authenticated multi-user agent API.
- Tests: normalization, scope isolation, correction invalidation, verified
  successes, deterministic clarification, replay and persistence/reopen.

The sidecar is deliberately independent of ordinary offline task operations.
No separate server, LLM subscription, embeddings or vector DB is needed.
An intent rule contains no credentials, code, SQL, direct Google Doc links,
or executable tool-call payloads.

### Reproduction (synthetic example)

```bash
cargo run -p shiori-cli -- intent-correct "make a note of this" \
  --meaning "Append a timestamped third-person entry in the active journal" \
  --procedure journal.append --workspace personal --project research \
  --evidence message.001
cargo run -p shiori-cli -- intent-resolve "MAKE A NOTE OF THIS!" \
  --workspace personal --project research
# Record only a genuine host-verified success using the returned rule ID/revision:
cargo run -p shiori-cli -- intent-success RULE_ID --if-revision 1 --evidence outcome.001
```

After one verified success, the next occurrence still requests clarification;
after two, it returns an established interpretation. Neither outcome executes
`journal.append`: the execution registry, authorization and user confirmation
still govern any proposed document mutation.

## Future shared application + MCP contract (NOT deployed)

These operations must be implemented in the common authenticated application
service before being exposed as separately named MCP tools:

| Named operation | Effect | Required evidence |
| --- | --- | --- |
| `intent.resolve` | Read | authenticated scope + active project |
| `intent.correction.propose` | Read/proposal | original user utterance and candidate mapping |
| `intent.correction.record` | Write | trusted user correction ID, reviewed memory policy |
| `intent.outcome.record` | Write | verified procedure execution receipt + expected revision |
| `intent.rules.list` | Read | workspace-scoped listing |
| `intent.rules.revoke` | Write | authenticated owner request + expected revision |

Model providers and MCP clients receive interpretations and clear clarification
requirements; they **do not** get to write the backing SQLite directly.
The source `workspace_id` and evidence provenance must come from a trusted host.
An MCP `intent.resolve` must never expose another workspace's learned language.

A returned `procedure_id` is an opaque reference to a host-owned,
versioned registry. Registered procedures validate parameters, scope,
available integrations, credentials and required user consent independently.
Remembered preferences must not bypass Google/ClickUp write approvals, secrets
protection, external side-effect checks or any authorization requirement.

## Required next passes

1. Integrate this port into SHIORI's planned shared Rust application services
   and user preference settings, not directly into model instructions.
2. Add real correction proposal/record UX and correction undo, source inspection,
   rule editing, privacy controls and memory export/delete.
3. Prove host-verified execution receipts, not model-reported "success" alone.
4. Add conflict tests, stale-source changes, offline/replay resilience,
   multi-owner permissions and sidecar backup/restore.
5. Register individually typed operations in `operations.v1.json`, then expose
   them through the authenticated SHIORI MCP **only after** the canonical service
   and sync boundaries are operational.
6. Evaluate Elara-style lexical/semantic association as *reversible retrieval
   hints* with original evidence, without automatically inferring hidden meanings.
7. Consider configurable clarification thresholds after measuring erroneous
   automations versus unnecessary questions. Never silently auto-authorize edits.

## Existing work

Source of salvage: Elara Angelic Utility Applet
`src/memory/observation.ts`, `retrieval.ts`, `semantic-file.ts`,
`organic-observer.ts`; Elara Relay `src/ai/memory-provider.ts`.
The Rust feature is a conceptual adaptation, not a direct TypeScript import.

**Invariant:** a correction can change what an expression *means*, never what
the assistant is *permitted to do*.
