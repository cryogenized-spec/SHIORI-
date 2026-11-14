# SHIORI / 栞

Local-first task management, independent of AI, account providers, and hosting services. A Rust-first project with the ELF//SHELL visual identity.

## Status

**Early implementation, not a public release.** This branch includes the Rust task model, SQLite persistence, a local CLI, the interactive web prototype, and a **development-only localhost adapter** that connects the browser to the real Rust CLI and SQLite database. This is not a public REST/MCP service, authenticated multi-user application, or finished sync/backup system.

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

By default the local CLI stores data in `~/.local/share/shiori/tasks.sqlite3`; override with `--database /path/to/tasks.sqlite3` or `SHIORI_DB`. SQLite works offline. `remove` is a soft delete for later synchronization support. Existing pre-versioning and v1 SQLite files are upgraded transactionally to schema version 3 while retaining task records and tombstones; unknown future schema versions are refused rather than overwritten. Full multi-version migrations and safe live backup are still future work.

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
