# SHIORI quality gates, performance and privacy

CI is designed to be reviewable and fail closed on formatting, warnings, Rust tests,
release builds, security advisories, automated browser interactions, and initial
synthetic SQLite latency budgets. Workflow actions are pinned to immutable SHAs;
GitHub tokens are read-only. There is no `pull_request_target` and no unreviewed
remote shell installer. Weekly runs retain perf artifacts for trend inspection.

## Reproducibility gap to resolve before merge

The first Rust implementation branch did not include `Cargo.lock`, and the
container used for preparing this work has no Cargo/rustc nor external network.
The CI bootstrap currently generates a lock and publishes it as an artifact;
**maintainers must commit the generated Cargo.lock** and then remove the bootstrap
fallback so all jobs fail on a missing/modified lock. Never mistake a runner-
generated lock for fully reproducible dependency resolution. Toolchain is pinned
at `rust-toolchain.toml` (1.99.1). The Python UI runner pins Playwright.

## Local developer commands

```bash
cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo test --workspace --all-features --locked
cargo build --workspace --release --locked
cargo install cargo-audit --version 0.23.0 --locked
cargo audit --file Cargo.lock --deny warnings
cargo run --release --locked -p shiori-perf -- --rows 3000 > rust-perf.json
python3 tests/perf_gate.py rust-perf.json
python3 -m unittest discover -s tests -p 'test_*.py'
python3 -m pip install 'playwright==1.56.0'
python3 -m playwright install chromium
python3 tests/ui_smoke.py --report browser-metrics.json
```

## What is measured

- **Rust SQLite probe:** open latency, indexed point lookup, project filter,
  due-date filter, and text search over 3,000 deterministic synthetic tasks.
  Each operation has warmups and 40 timed runs; p50/p95/p99 are recorded.
- **Browser smoke:** desktop (1440px) and phone (390px), console errors,
  calendar open/close and preference persistence, month controls, task capture,
  local demo persistence, overflow, navigation timings, and toggle p95.
- **Quality checks:** Rust formatting, strict Clippy, unit/integration/doc tests,
  release compile, advisory scan, coverage artifact, Python test harness.

The initial SQLite budgets are **broad hard limits** to catch major regressions,
not a scientifically calibrated baseline. GitHub's shared runners are noisy.
Compare p95 trends only on matching runner/fixture/toolchain conditions; calibrate
limits after multiple successful runs. Do not advertise absolute startup times
until tested on physical low-spec Android and Linux machines. Do not use synthetic
benchmarks as evidence of end-to-end app startup performance.

## Privacy

No production analytics collection is implemented. No user task titles, notes,
attachments, identifiers or device diagnostics are uploaded. CI creates its own
synthetic fixtures. Future app diagnostics should be **opt-in**, stored locally by
default, expose a clear Export/Delete button, and redact identifiers. A telemetry
service must remain optional and never block task management.

## Additional test strategy

Prioritize (1) property-based task/recurrence invariants; (2) migration and
backup/restore round-trips; (3) conflict convergence with offline multi-device
simulation and tombstones; (4) security authorization tests for REST/MCP,
including cross-tenant access; (5) load and rate-limit testing; (6) axe-core
accessibility audits and Android TalkBack checks; (7) fuzzing parsers/recurrence;
(8) Miri or Loom for concurrency; (9) mutation testing; (10) platform startup,
memory, battery, and filesystem performance on actual devices.

## Required GitHub branch protection (manual repository configuration)

The connector has no authorized branch-rules write operation. In GitHub Settings
→ Rules → Rulesets, protect `main`: require PR review, require status checks
`Rust quality`, `Rust dependency audit`, `Rust coverage`,
`Browser UI and accessibility smoke`, and `SQLite performance budget`; require
branches to be current, forbid force-push/delete, and prohibit bypass where
possible. Avoid enforcing reviewer counts that the single maintainer cannot
satisfy until another reviewer is available. Confirm required check names after
GitHub Actions first creates them. Workflow-file and core changes are CODEOWNERS-
assigned, but CODEOWNERS alone is not branch protection.
