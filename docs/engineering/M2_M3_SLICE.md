# M2/M3 implementation slice — 2026-11-12

This is a staged, reviewable prototype built on PR #1. **It does not complete M2 or M3.** In particular, there is not yet a production web-to-Rust connection, assignment identity, multi-device sync, calendar import, saved schedule application, native Android UI or named-timezone/DST scheduling.

## M2: local daily-workflow starter

- The web **demo** has a "My attention" view: open tasks that are overdue/due today, marked high-priority, or in progress. It states that user assignment and sync are unavailable; it must not be described as SH-001 "Assigned to Me" until identity and assignments are implemented.
- A saved list ordering selector offers focus, due date, priority and FIFO. For initial bundled sample tasks (which lack creation timestamps), FIFO uses their original array order; browser-captured demo tasks are timestamped. These browser preferences and tasks remain exclusively in localStorage, not SQLite.
- The Rust CLI provides `attention --on YYYY-MM-DD` using the same **local-only** due/priority/status predicate. No identity or permission boundary is inferred.

## M3: local one-day deterministic time-block preview

The pure Rust `shiori_core::scheduling::plan_day` accepts explicit UTC windows, occupied intervals, task IDs, duration estimates, priorities, due calendar days, and prerequisite IDs. It generates nonoverlapping proposals, schedules completed prerequisites first (or requires them in `completed_ids`), and returns all unscheduled tasks with either `NoCapacity` or `BlockedByDependency`. The operation does not write to tasks or modify calendars, and it needs no network, AI or API key.

For a CLI demo using a **fixed** UTC offset (120 minutes is South African Standard Time), run:

```bash
cargo run --locked -p shiori-cli -- attention --on 2026-11-12
cargo run --locked -p shiori-cli -- plan 2026-11-12 \
  --start 08:00 --end 17:00 --break-start 13:00 --break-end 14:00 \
  --utc-offset-minutes 120 --default-minutes 30
```

The CLI does not yet store task duration estimates or dependencies: each pending task receives the supplied default duration, and its prerequisite list is empty. The pure planner supports prerequisite sequences for later wiring. The offset flag is deliberately explicit; **a fixed UTC offset does not substitute for IANA timezone rules or DST**. The caller must supply correctly interpreted UTC windows. Never apply this preview directly to a user's calendar without review.

### Validation and future work

CI runs Rust formatting, strict lint, unit/integration tests, release build, browser regression, SQLite performance, coverage and dependency audit. Regression tests cover overlapping occupied time, priority ordering, unschedulable overflow, missing/cyclic prerequisites, completed prerequisites, bad IDs/durations, attention rendering and saved FIFO selection.

Remaining M2/M3 exit gates: identity/assignment model with actual fast indexed Assigned to Me queries and freshness indicators; native offline client/UI wired to Rust; durable saved views and notifications; stored duration and dependency graph with cycle rejection; configurable recurring work hours per user and holiday/timezone policies; busy-time calendar adapters; splitting and pinning; preview/apply/undo with conflict handling; and end-to-end device benchmarks.
