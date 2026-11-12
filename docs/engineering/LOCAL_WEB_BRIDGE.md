# SHIORI local web bridge — development slice

**Status: development-only integration, not a production API.**

This milestone proves that the same Rust task/domain/SQLite engine powering the CLI can back the web prototype. The web page stays visually independent of the persistence engine; the Python standard-library adapter is a temporary localhost transport and calls the compiled Rust CLI for **every** read/write. It never opens SQLite or implements independent task rules.

## Launch (Linux, local workstation)

```bash
cargo build --locked -p shiori-cli
python3 apps/local_bridge.py \
  --cli target/debug/shiori-cli \
  --database "$HOME/.local/share/shiori/tasks.sqlite3" \
  --port 8765
```

Open **http://127.0.0.1:8765**. The footer indicates **LOCAL RUST / SQLITE · OFFLINE** once connected. Existing CLI records are displayed; no bundled sample records are copied into the SQLite database. Browser sample tasks remain isolated in `shiori-demo-tasks` localStorage and are never silently imported.

If you instead open `apps/web/index.html` directly, or use a plain Python static web server, the browser continues in **STATIC DEMO** mode. Neither mode needs an AI key or external service.

## Supported operations

- Read active SQLite tasks, including notes, due calendar date, status, project, priority, effort estimate, and record revision, using a versioned length-prefixed UTF-8 export from Rust (no fragile stdout table parsing).
- Create tasks through the existing Rust validation/SQLite storage path, with notes, priority, due date and optional estimate.
- Complete/reopen tasks or move them between **To do**, **In progress**, and **Done**. Changes persist across browser refresh and application restarts.
- Read calendar, attention, search, reports and project views from the *same* current SQLite snapshot. The interface's display-only settings (theme, calendar collapsed state, FIFO order) remain local browser preferences.

## Local security and non-goals

The temporary development server binds **only to 127.0.0.1**. It checks the HTTP `Host` on reads/writes, requires a matching `Origin` on writes, rejects non-JSON write requests, bounds request/snapshot sizes, sets conservative response security headers, and serves application assets from a fixed public directory. The server executes only a fixed allowlist of Rust CLI commands without a shell.

**This is NOT a secure authenticated API**: other local processes can make loopback requests and can spoof HTTP headers. Do not use the bridge on a shared or untrusted workstation, expose it through reverse proxies/tunnels, bind it to a public address, or treat it as production MCP/REST.

The long-term Rust-native adapter still requires authenticated local identity, scoped project permissions, CSRF controls, revision-based writes, audit logging, rate limits, backup/recovery, standardized error schemas, and independent threat-model review. A temporary Python subprocess adapter is intentionally not an Android, hosted or production architecture decision.

Other remaining work: task editing and removing from the browser; persisted assignment-aware attention queries, notification UX, safe backup/restore, scheduling apply/undo, real calendar busy windows, named timezone/DST policies, native clients and sync.

## Automated coverage

`tests/local_bridge_smoke.py` spins up a loopback server against a temporary real SQLite file and compiled CLI. It exercises initial empty state, task creation with multiline Unicode notes and estimate, status transitions and revisions, persistence after server restart, and rejection of hostile Host/Origin, form submissions and invalid task titles.

Existing static browser smoke/a11y tests continue running and must not regress. Tests for end-to-end Playwright interactions against the *live* bridge are still a follow-up.
