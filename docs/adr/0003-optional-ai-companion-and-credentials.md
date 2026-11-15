# ADR 0003 — Optional in-app companion, dock and credential boundary

Status: **Design accepted for experiment, production integration not implemented** (2026-11-15)

Related: [SHIORI ROADMAP](../../ROADMAP.md), [ADR 0002](0002-application-ports-and-provider-boundaries.md), [foundation gates](../engineering/FOUNDATION_EXTENSION_GATES.md).

## Decision

SHIORI remains a usable independent local-first task manager without an LLM. Offer a separately enabled **in-app AI Companion** that can share the same authenticated task/graph application operations as the remote SHIORI MCP. An in-app assistant does not automatically grant ChatGPT account entitlements, provide ChatGPT login, or reuse ChatGPT subscription billing. This feature must never require an embedded API key or unrestricted model-written code.

### Dock and interaction contract

- The assistant opens as a resizable **edge-anchored panel** from right, left, top or bottom, selected by the nearest screen boundary to a draggable floating launcher.
- Collapse returns to the draggable launcher without losing thread state. The launcher snaps to the closest screen edge, stays keyboard-accessible, and may be dismissed by dragging to an animated trash target. The persistent header command always restores the panel without losing chats.
- The panel has a thread drawer, create/switch/delete thread actions, scroll-to-latest messages, a pinned input area, optional local scene context, and clear status indicators for unconfigured, connected, offline, waiting and error.
- Store docking preference, last selected thread, dimensions, and launcher position independently from canvas position and task data. Respect touch, keyboard, reduced-motion and mobile safe areas. The panel must not require the user to switch into the ChatGPT application.
- The **composer controls** include only model preferences: grouped currently served vs. older OpenAI API model IDs, reasoning effort, max output tokens, a soft minimum output length target, verbosity, and model-aware creativity/temperature if the API supports it. Use named balanced/economy/deep/writing presets. Validate against the actual backend's supported catalogue at connection time. Hide or disable invalid parameters rather than passing them to an API and producing a 400 error.
- **Universal Settings**, separate from the composer, owns the provider account, authentication, key-management/setup status, privacy, session/device revocation, data export and deletion. The companion never asks users to paste API keys into a chat, scene JSON, query parameter or browser storage.

### Secret ownership, deployment and billing

- A user opting into a Cloudflare deployment provisions **their own Worker and Cloudflare account**, or a compatible self-hosted proxy, to avoid consuming the developer's quota and to avoid collecting third-party data. The **OpenAI key is stored only in that backend's encrypted secret binding**, such as `OPENAI_API_KEY` in Cloudflare Workers Secrets. Do not use Worker plaintext vars or a committed environment file for secrets.
- A browser-facing API must verify **user identity and session**, token audience, server-side scopes, request size/rate/budget, account ownership, and origin/CSRF protections where relevant. A CORS allowlist alone is not authentication. Provider requests originate from the trusted server; the model key is never returned to clients. A native client stores revocable auth/session credentials using an OS-secured store (Android Keystore or desktop secret service), **not WebView localStorage**.
- Allowlist OpenAI model IDs/capabilities, enforce effective output/token budget server-side, and proxy Responses API requests. Prefer explicit, typed tool calls into shared SHIORI application services. Do not enable arbitrary model-originated network access or SQL. Revalidate permissions and revisions on every mutation and show a visual preview/diff before consequential changes.
- Worker deployments must not be publicly usable without authentication. Set cost ceilings, per-user budgets, request concurrency, logs without secrets/prompts by default, and safe key rotation/revocation. Do not share a single Cloudflare Worker secret across unrelated users unless a future multi-tenant architecture has been independently audited.
- ChatGPT via SHIORI MCP and the optional in-app companion are separate user experiences but **must reuse the same authorization-protected application service layer**. SHIORI may work offline with no AI account.

### Chat persistence

- Production assistant threads, message revisions, drafts, attachments, model/preset choices and linking to the current graph scene must use a durable, migration-tested SHIORI store and explicit retention/export/delete policies. Sensitive chats require appropriate encryption/key management. Never confuse *a local draft* with a successfully delivered model response.
- The current standalone HTML prototype's `localStorage` is **for disposable demonstration data only**. It has no model connection, Cloudflare credentials, verified storage guarantees, or backend. Do not use it for genuine confidential correspondence.
- Streaming, cancellation, reconnect/response retry, token cost reporting, duplicate-send protection and scoped MCP/app commands need independent regression and threat-model tests before release.

### API settings policy

Supported OpenAI parameters and models change. The [live models catalogue](https://developers.openai.com/api/docs/models), [reasoning guide](https://developers.openai.com/api/docs/guides/reasoning), and [Responses reference](https://developers.openai.com/api/reference/resources/responses/methods/create) are authoritative. Only present `temperature` for specifically supported model/effort combinations; for example older GPT-5.4 allows temperature only with `reasoning.effort=none`. `max_output_tokens` exists; no generally supported strict `min_output_tokens` equivalent exists, so treat that slider as a *soft target* in the app's prompt layer, not a guaranteed API control. Model availability must be verified for the user's actual API account.

### Implementation slices

1. Prototype dock UI alongside the offline 2D ISW: all four edges, resize, collapse, draggable/snap launcher, animated trash dismissal and header recovery, persistent local mock threads, model-catalogue settings, and universal-settings entry. **No provider calls or keys**.
2. Define a typed, capability-aware provider interface and production thread storage; migrate from disposable test fixtures only with confirmed backup/restore and no secret copies. Add device-level identity, secret and session protocols.
3. Build an independently deployable, reviewed reference backend (Cloudflare Worker or equivalent) with authenticated pairing, explicit OAuth/session handling, rate limits, budget caps, server-held OpenAI key and audited Responses API calls. Offer an easy setup guide without silent hosting or cost.
4. Integrate read-only scene context, safe Responses streaming and named operations with cancellable execution. Distinguish assistant-generated proposals from applied SHIORI modifications.
5. Gate actual graph/task/inbox/automation writes behind application command validation, permission checks, revision preconditions and a user-approved scene diff. Test multiple threads, provider failures, accidental duplicate sends, revoked accounts, unsupported models, and mobile touch/collision handling.

The dedicated AI assistant is an **optional feature** and is not required for Shiori's first local/offline release. Reference screenshots and the locally generated v0.4 interactive proof demonstrate only the UI; they are not evidence of a functioning OpenAI API or production ChatGPT MCP connection.
