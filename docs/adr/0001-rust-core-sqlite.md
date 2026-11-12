# ADR 0001 — Portable Rust core and local SQLite storage

Status: **Accepted for the first implementation slice** (2026-11-11)

## Context

SHIORI needs dependable task operations without AI, an external server, or a proprietary cloud service. MCP, REST, mobile, and UI are adapters to shared domain operations; none should own task rules.

## Decision

- Rust 2024 edition with small workspace crates, starting with `shiori-core` (pure domain), `shiori-storage` (SQLite adapter), and `shiori-cli` (local test interface).
- Domain IDs are locally generated UUIDv7 identifiers.
- `due_on` is a **calendar date**, not UTC midnight; created/updated/completed timestamps are UTC instants.
- SQLite uses prepared statements, migrations or schema versioning in a subsequent slice, indexed queries, optimistic version checks, and soft-delete tombstones.
- No mandatory network or provider-specific dependencies. No MCP or REST endpoints until authentication, authorization and auditing have contracts.
- Default local data path follows XDG on Linux. Explicit `--database` allows alternate locations.

## Follow-up before 0.1 release

1. SQLite schema v2 now performs transactional v0→v1→v2 upgrades, retaining old tasks and tombstones, and adds validated effort estimates and prerequisite edges. Before v0.1 release, extract embedded SQL into numbered migration files, expand corrupted-schema/rollback tests and implement documented safe online backup/recovery.
2. Make the persistence trait explicit, introduce scoped user identity and project ownership, and add transaction boundaries.
3. Specify recurrence, dependency acyclicity, work schedules, time zones and conflict semantics.
4. Build an authenticated loopback-first API used by desktop/Android and an independently authenticated MCP adapter.
5. Benchmark realistically sized local fixtures and test concurrency, backups and recovery.
6. Finalize AGPLv3 licensing and contribution policy before distributing binaries.

## Alternatives considered

Full reuse of Vikunja/tududi would import backend assumptions, licensing choices and features beyond our target. SQLite is intentionally the local store; PostgreSQL can later serve a multi-user deployment through an independently verified adapter.
