# SHIORI / 栞

Local-first task management, independent of AI, account providers, and hosting services. A Rust-first project with the ELF//SHELL visual identity.

## Status

**First implementation slice, not a public release.** This branch implements a Rust task model, SQLite persistence, a local CLI and an interactive web **mockup**. The web UI still uses browser sample data; it is **not yet connected** to Rust, a REST API, or MCP. There is no authentication, sync, or production-grade migration system yet.

## Development

Requires Rust **1.99.1** or newer and Cargo. On Linux:

```bash
cargo test --workspace
cargo run -p shiori-cli -- add "Review SHIORI task model" --project Development --priority high --due 2026-11-12
cargo run -p shiori-cli -- list
# Edit without overwriting other fields; remove due date explicitly:
cargo run -p shiori-cli -- edit <task-id> --notes "Review the roadmap" --project Development --priority urgent --clear-due
# Optionally require the revision displayed by "show" or a previous edit:
cargo run -p shiori-cli -- edit <task-id> --title "Revised" --if-version 2
```

By default the local CLI stores data in `~/.local/share/shiori/tasks.sqlite3`; override with `--database /path/to/tasks.sqlite3` or `SHIORI_DB`. SQLite works offline. `remove` is a soft delete for later synchronization support. Existing pre-versioning SQLite files are baselined transactionally to schema version 1 while retaining tasks and tombstones; unknown future schema versions are refused rather than overwritten. Full multi-version migrations and safe live backup are still future work.

The web design concept runs standalone in Firefox by opening `apps/web/index.html`, or via a local static server:

```bash
cd apps/web && python3 -m http.server 8765 --bind 127.0.0.1
```

The optional calendar on **My day** can be collapsed; its state is saved in local storage. Select a date to filter the task list for that day, and select **Today** to reset.

## Layout

- `crates/shiori-core`: standalone task domain rules
- `crates/shiori-storage`: SQLite adapter with indexed filters and tombstones
- `apps/shiori-cli`: manual offline task operations
- `apps/web`: responsive browser mockup (not linked to backend)
- `docs/adr`: architecture decisions
- `.github/workflows`: automated formatting, lint and tests

This project follows the existing `ROADMAP.md`. Dependency and licence review remain mandatory before distribution; AGPLv3 is proposed, not yet finalized.

## Quality, performance, CI

See [`docs/engineering/QUALITY_AND_PERFORMANCE.md`](docs/engineering/QUALITY_AND_PERFORMANCE.md) for the strict CI pipeline, synthetic SQLite benchmarks and browser interaction tests. These produce aggregate performance reports as GitHub Actions artifacts; no real user telemetry is collected.
