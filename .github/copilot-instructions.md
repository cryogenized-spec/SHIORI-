# Working on SHIORI / 栞

Follow `ROADMAP.md`, the relevant ADRs in `docs/adr/`, and the appropriate agent skill in `.github/skills/` for the task. Only load skills that fit the change. Do not let bundled third-party example versions override the pinned toolchain, `Cargo.lock`, current official documentation or SHIORI's architecture.

Keep `shiori-core` free of database, network, UI and MCP dependencies; route all interfaces through shared domain services. Preserve offline-first behaviour, privacy, user-owned exports, and performance. Treat every new dependency and skill as reviewed supply-chain code; do not install or execute an upstream skill's scripts automatically.

For Rust code, prefer `shiori-rust-architecture`; for persistence/sync, `shiori-offline-data-integrity`; for MCP, `shiori-rust-mcp`; for UX, `shiori-visual-system`. Also use the imported security, GitHub Actions hardening, Playwright, or agent supply-chain skill when relevant.

Never silently relax CI gates or claim unimplemented features are functional. Keep changes on reviewable pull requests; do not merge without explicit human approval.
