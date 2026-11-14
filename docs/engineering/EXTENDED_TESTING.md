# SHIORI extended test strategy

## Active tests in pull-request checks

- **Generative property/invariant tests:** a fixed-seed randomized Unicode title generator, status transition generator, enum round-trips, and invalid-rename atomicity. Self-contained tests use no new runtime dependencies.
- **Cold database restore/restart:** verifies a safely closed SQLite file copy preserves active records, completion timestamps, versions and tombstones. **This is not a live backup or a migration suite**; neither capability has been implemented yet.
- **Automated accessibility:** axe-core WCAG A/AA checks at desktop and mobile widths. Serious/critical issues fail CI and results are uploaded. A manual screen-reader/keyboard review is still required.
- **Existing checks:** formatting, strict Clippy, unit/integration/doc tests, release builds, RustSec, coverage, interactive browser flow, a **60% minimum Rust line-coverage gate**, and a synthetic 3,000-task SQLite performance budget.

## Scheduled/manual deep testing

A separate GitHub Actions workflow runs: cargo-fuzz (bounded libFuzzer sessions for untrusted title strings), cargo-mutants (Rust unit-test sensitivity), and a larger synthetic 30,000-task SQLite benchmark. These do not replace required PR checks. Expensive deep tests run on demand and weekly once this workflow reaches the default branch.

## When new components exist

- **Synchronization:** disconnected edits, divergent revisions, duplicate and out-of-order replay, conflicts, delete/restore and reconnection. Not enabled until actual sync code exists.
- **MCP/REST:** scope enforcement, IDOR authorization tests, malformed requests, cancellation, rate limits, idempotency, explicit destructive confirmation and protocol conformance. Not enabled until services exist.
- **Android:** Macrobenchmark cold/warm starts, scroll jank, memory, battery and accessibility with physical-device validation. Not enabled until Android app exists.
- **Database migrations:** upgrade and rollback compatibility fixtures for every schema version; mandatory before a migration feature ships.
- **Live backup:** proper SQLite online backup or VACUUM INTO with restore verification once a safe export API is implemented.
- **Hardware profiles:** repeat benchmarks on baseline Android hardware and low-resource Linux devices; GitHub-hosted runner results are not real-world speed guarantees.

## Privacy

Only synthetic fixture data enters test artifacts. No task titles, account identifiers or telemetry from actual users is uploaded by these test workflows. A later in-app diagnostics panel should remain local-only and opt-in for export.
