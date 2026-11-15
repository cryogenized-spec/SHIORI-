# SHIORI / 栞

Local-first task management, independent of AI, account providers, and hosting services. A Rust-first project with the ELF//SHELL visual identity.

## Status

**Early implementation, not a public release.** This branch includes the Rust task model, SQLite persistence, a local CLI, the interactive web prototype, and a **development-only localhost adapter** that connects the browser to the real Rust CLI and SQLite database. The local bridge is not a public REST/MCP service or finished sync/backup system. A separate single-owner Cloudflare MCP alpha now exists, but it is not synchronized with the local Rust store.

## Development

Requires Rust **1.99.1** or newer and Cargo. On Linux:

```bash
cargo test --workspace
cargo run -p shiori-cli -- add "Review SHIORI task model" --project Development --priority high --due 2026-11-12 --minutes 45
cargo run -p shiori-cli -- list
# Edit without overwriting other fields; remove due date explicitly:
cargo run -p shiori-cli -- edit <task-id> --notes "Review the roadmap" --project Development --priority urgent --clear-due
# Optionally require the revision displayed by "show" or a previous edit:
cargo run -p shiori-cli -- edit <task-id> --title "Revised" --if-version 2
# Link prerequisites, edit a stored estimate and inspect task relationships:
cargo run -p shiori-cli -- depends <task-id> --on <prerequisite-task-id>
cargo run -p shiori-cli -- edit <task-id> --minutes 75
cargo run -p shiori-cli -- show <task-id>
# Single-user local assignment identity (not a login or permission model):
cargo run -p shiori-cli -- edit <task-id> --assign-to local
cargo run -p shiori-cli -- edit <task-id> --unassign
# The browser's Assigned to me panel reads indexed SQLite assignments,
# distinguishing waiting-on-prerequisite tasks from actionable work.
# Local-only attention and a side-effect-free scheduling preview:
cargo run -p shiori-cli -- attention --on 2026-11-12
cargo run -p shiori-cli -- plan 2026-11-12 --start 08:00 --end 17:00 --break-start 13:00 --break-end 14:00 --utc-offset-minutes 120 --default-minutes 30
```

By default the local CLI stores data in `~/.local/share/shiori/tasks.sqlite3`; override with `--database /path/to/tasks.sqlite3` or `SHIORI_DB`. SQLite works offline. `remove` is a soft delete for later synchronization support. Existing pre-versioning, v1 and v2 SQLite files are upgraded transactionally to canonical schema version 3 while retaining task records and tombstones; unknown future schema versions are refused rather than overwritten. Full multi-version migrations and safe live backup are still future work.

The web design concept runs standalone in Firefox by opening `apps/web/index.html`, or via a local static server (demo tasks only):

```bash
cd apps/web && python3 -m http.server 8765 --bind 127.0.0.1
```

**To use real tasks from SQLite rather than sample records**, build the local Rust CLI and launch the development bridge:

```bash
cargo build --locked -p shiori-cli
python3 apps/local_bridge.py --cli target/debug/shiori-cli --port 8765
```

Open `http://127.0.0.1:8765`. The footer changes to **LOCAL RUST / SQLITE** when connected. The bridge binds only to loopback, invokes Rust CLI operations, and does not import demonstration tasks. The local **Assigned to me** view uses an indexed SQLite query for the `local` identity and exposes dependency blockers and local-read freshness. Assignment IDs are not authentication or multi-user permissions; older task records remain unassigned until explicitly assigned. **Development only:** it is not an authenticated remote service; do not expose it to your LAN, a proxy or a tunnel. For the threat model, limitations and `--database` override see [local web bridge](docs/engineering/LOCAL_WEB_BRIDGE.md).

The optional calendar on **My day** can be collapsed; its state is saved in local storage. Select a date to filter the task list for that day, and select **Today** to reset.

**M2/M3 development slice:** the browser prototype now has a **local attention preview** and saved FIFO/due/priority ordering. The offline CLI can preview deterministic workday blocks with a fixed UTC offset and explicit break. These features are deliberately limited: the standalone browser mode still uses demo data, while the optional development bridge exposes local SQLite assignments (not authenticated multi-user permissions); there is no authenticated production API; task durations and prerequisite links are stored in SQLite and used by the CLI planner, while an optional development-only localhost bridge allows the web prototype to view and mutate that same task database. There is no real calendar write or DST-aware time zone engine. See [M2/M3 slice and remaining exit criteria](docs/engineering/M2_M3_SLICE.md).

## Remote operations and SHIORI MCP status

An initial [Cloudflare MCP alpha](cloudflare/shiori-mcp/README.md) is provisioned at `https://shiori-mcp-alpha.cryogenized.workers.dev/mcp`, with **nine** deployed bearer-protected tools and dedicated JSON/HTTP routes. The source and in-memory D1 integration tests pass. **Independent live network checks now confirm its health endpoint and refusal of unauthenticated MCP requests**, while authenticated remote tool calls still need verification. It does **not** support OAuth, ChatGPT connection, or synchronization with local Rust/SQLite tasks. Cloudflare D1 is an isolated remote dataset. See [ADR 0004](docs/adr/0004-remote-operation-registry-and-mcp.md) and the [per-operation registry](docs/api/operations.v1.json). Entries marked `planned` remain unavailable. Never expose the existing Python local bridge publicly.

## Infinite Spatial Workspace — Rust-backed alpha

The existing desktop task board retains its own navigation. The **Spatial canvas** link opens `isw.html`; when the local Rust bridge is running on loopback, the canvas reads real SQLite task records and verified prerequisite links. The **Live Rust** control refreshes it. The old board remains available through **← Board**.

**Implemented against Rust:** task import/read, real stored dependency edges, and visual card positions in a separate, versioned SQLite sidecar (`tasks.isw.sqlite3`, view schema v1) with optimistic view revision checks. The canonical task database remains at schema v3 and is unchanged by the ISW extension. Creating a **Task** on the live canvas calls the existing local Rust task service and saves its view position. Moving a card **never alters task status, version or prerequisites**. Layout starts locked; users must explicitly unlock and enter Move mode.

**Still illustrative in the HTML:** non-task artefacts and arbitrary links, comments/activity/automations, external GitHub import, EAI-generated responses, chat messages and model/API interactions. The optional AI dock is a visual-only preview; there is no backend key storage, user login, authenticated model connection, or MCP service in this slice. Drawing a link in fixture mode must not be treated as a real task dependency.

Canvas controls retained from v0.5: circuit/curved/straight connectors, pan/zoom, pinch protection, map-marker semantic zoom, minimap, full artefact sheet and preview EAI stage. Android-native ISW integration remains separate future work.

CI workflow **SHIORI Rust-backed ISW snapshot** compiles the Rust CLI, seeds a temporary fictional offshore task graph, checks the local bridge, and uploads desktop/mobile screenshots. It never uses real task data.

**Security:** the local bridge is a development adapter bound to 127.0.0.1; do not expose it to a public hostname, LAN or tunnel.

## Layout

- `crates/shiori-core`: standalone task domain rules
- `crates/shiori-storage`: SQLite adapter with indexed filters and tombstones
- `apps/shiori-cli`: manual offline task operations
- `apps/web`: responsive browser UI (static demo or optional localhost Rust/SQLite bridge)
- `apps/local_bridge.py`: temporary development HTTP adapter; not a public REST API
- `docs/adr`: architecture decisions
- `.github/workflows`: automated formatting, lint and tests

This project follows the existing [`ROADMAP.md`](ROADMAP.md). Dependency and licence review remain mandatory before distribution; AGPLv3 is proposed, not yet finalized.

## Extensible architecture

[`ADR 0001`](docs/adr/0001-rust-core-sqlite.md) defines the local Rust/SQLite base. [`ADR 0002`](docs/adr/0002-application-ports-and-provider-boundaries.md) defines the application-service, inbox, MCP and external provider boundaries, with the [`foundation extension gates`](docs/engineering/FOUNDATION_EXTENSION_GATES.md) guiding future changes. The new `shiori-core::inbox` module defines local SH-005 capture/triage/link/archive rules and tests only; **persistent inbox operations, user-facing inbox screens, MCP and ClickUp integration are not yet implemented**.

## Quality, performance, CI

See [`docs/engineering/QUALITY_AND_PERFORMANCE.md`](docs/engineering/QUALITY_AND_PERFORMANCE.md) for the strict CI pipeline, synthetic SQLite benchmarks and browser interaction tests. These produce aggregate performance reports as GitHub Actions artifacts; no real user telemetry is collected.
