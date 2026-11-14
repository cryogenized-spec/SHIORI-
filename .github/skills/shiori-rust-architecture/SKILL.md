---
name: shiori-rust-architecture
description: Develop, refactor, or review the SHIORI Rust workspace, task domain, SQLite adapter, CLI, and future API while enforcing modular boundaries, current dependency practices, performance targets, and safe data handling. Use for any Rust feature, crate design, domain-model change, database query, or performance optimization in SHIORI.
---

# SHIORI Rust architecture

Read `ROADMAP.md`, `docs/adr/`, and the relevant crates before changing architecture. Keep changes incremental, reviewable and specific to the requested feature.

## Boundaries

- `crates/shiori-core`: pure task-domain models and deterministic validation; do not add UI, SQL, network, filesystem, hosting, or MCP dependencies.
- `crates/shiori-storage`: SQLite repository, migrations, indexed queries and tombstone persistence. No presentation concerns.
- `apps/shiori-cli`: thin interface over application/domain services. Do not duplicate task logic here.
- Future Rust API, synchronization, scheduling and MCP adapters must call the same domain/application services; never bypass permission checks via direct SQL.
- Introduce new crates only for durable, cohesive boundaries. Avoid all-purpose utility crates and giant modules.

## Data invariants

- Retain stable task IDs and separate created, planned-start, actual-start, due, completion and deletion timestamps.
- Use explicit UTC storage and well-defined timezone/calendar conversion at boundaries; never reinterpret date-only values as local timestamps.
- Validate inputs at boundaries and preserve atomicity for failed edits. Check transactional changes, indexes and migrations before shipping.
- Offline operation is required; never assume a network request or hosted account exists.
- Prevent data loss: preserve tombstones for later sync, provide backups and migration tests before destructive schema changes.

## Implementation gate

1. Identify impacted crates and invariants. Write an acceptance test demonstrating the failure or feature first.
2. Use the pinned Rust toolchain and maintain committed `Cargo.lock` for this application workspace. Research maintained crate versions before adding dependencies; don't copy versions from old skill templates.
3. Run `cargo fmt --all -- --check`, `cargo clippy --workspace --all-targets -- -D warnings`, `cargo test --workspace --locked`, and release-build smoke checks.
4. Extend SQLite performance probes for query-path changes; explain measured p50/p95 results and environment.
5. Never weaken CI, coverage gates or benchmarks to force a passing run. Report limitations and open decisions.

Avoid claiming cross-device sync or a public API works while those components remain unimplemented.
