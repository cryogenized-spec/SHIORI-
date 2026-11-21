# SHIORI / 栞

**Local-first, Rust-first task management** with an infinite spatial workspace, optional AI and an authenticated Model Context Protocol (MCP) interface. SHIORI is independent of ELF//SHELL and CiRYVA, although it shares their visual design direction. Ordinary offline task management must not require an AI model, online account or Cloudflare.

## Project status — 21 November 2026

**Engineering alpha / private development. Not a production release or an automatically synchronized multi-device task manager.** Rust/SQLite, Android offline shell and owner-operated Cloudflare MCP remain separate by default. A narrowly scoped, owner-invoked, backed-up single-task cloud-to-Rust apply was merged as [S8 (#101)](https://github.com/cryogenized-spec/SHIORI-/pull/101), but **no background sync loop or physical two-device convergence has been enabled**. Do not assume Cloudflare and local tasks match.

| Area | Verified implementation | Still missing for a dependable release |
| --- | --- | --- |
| Rust core / storage | Jiff **1.0.0**, canonical SQLite schema **v3**, validated task CRUD, priorities, statuses, dependency cycle checks, indexed local attention, revisions and soft-delete tombstones | Full recurring work, calendar-backed scheduling, sync history/conflict UX, production backup/recovery acceptance |
| Desktop/web | Responsive prototype; optional **localhost-only** Rust CLI/SQLite adapter; real Rust-backed spatial task scene and separate versioned position sidecar | Authenticated production app service, durable inbox and full artefact graph; extensive user testing |
| Android | Bundled offline WebView shell, Rust JNI/SQLite working copy, guarded experimental native source/cutover and recovery paths; debug APK and three native ABIs build in CI | Physical-device release/upgrade tests, native source finalization; intermittent Android 15 real-touch emulator test **[#65](https://github.com/cryogenized-spec/SHIORI-/issues/65)** remains open |
| Remote MCP | **33 live OAuth-connected operations out of 126 defined**; OAuth **2.1 + PKCE** with scoped owner consent; merged and live-tested [#109](https://github.com/cryogenized-spec/SHIORI-/pull/109) resolves the old GitHub Actions approval blockage | **93 planned operations**; single-owner isolated D1, no multiuser server or automatic background replication |
| Synchronization | S1–S3 source/manifest and change-feed safeguards; S4 owner-explicit current D1 record plus private content preview; S5 version/provenance-pinned remote update and conflict planning; S6 original S2 source reconciliation; S7 private SQLite backup; merged **S8 one-task owner-approved cloud-to-Rust apply**, **S9 revision checkpoint**, and **S10 read-only two-device divergence review [#105](https://github.com/cryogenized-spec/SHIORI-/pull/105)**. [ADR 0005](docs/adr/0005-rust-cloudflare-sync.md) | Incremental owner-reviewed two-way transitions, full remote/local schema parity, conflict UX, safe rollback, offline queue reconciliation, recovery from interrupted apply, and two independent physical devices reaching convergence |

**Validation boundary:** the isolated Cloudflare workspace previously contained eight deliberately labelled demo tasks with seven prerequisite edges. S4–S9 acceptance uses **synthetic fixtures** and no real user-task transfer. The authenticated OAuth-connected resource now reports **33 live operations** (verified after deployment on 21 November 2026), including `sync.record.snapshot.read` and `sync.record.apply`; this does **not** prove two-device convergence. The Android real-touch defect remains tracked in [#65](https://github.com/cryogenized-spec/SHIORI-/issues/65), despite passing CI reruns.

**Detailed sync milestones:** [S8 explicit owner-reviewed local apply](docs/engineering/RUST_CLOUDFLARE_SYNC_S8_REVIEWED_APPLY.md) · [S9 post-apply revision checkpoint](docs/engineering/RUST_CLOUDFLARE_SYNC_S9_CHECKPOINT.md) · [S10 incremental review, merged PR #105](https://github.com/cryogenized-spec/SHIORI-/pull/105).

### Current implementation priorities

1. **Complete controlled multi-cycle synchronization:** build on merged S8 verified local apply and S9 checkpoint; use the merged [S10 checkpoint-based divergence review (#105)](https://github.com/cryogenized-spec/SHIORI-/pull/105) to plan an owner-reviewed update, then implement separate owner-reviewed local→remote CAS updates, atomic checkpoint transitions, explicit backup recovery and two-device offline acceptance without blind overwrites. See [#47](https://github.com/cryogenized-spec/SHIORI-/issues/47), [#72](https://github.com/cryogenized-spec/SHIORI-/issues/72) and [ADR 0005](docs/adr/0005-rust-cloudflare-sync.md).
2. **Finish Android acceptance:** resolve the recurrent genuine-touch input defect [#65](https://github.com/cryogenized-spec/SHIORI-/issues/65) with repeat emulator and physical-device verification; test offline upgrade/backup paths and finalize durable native storage. The capture-phase pointer diagnostic [#104](https://github.com/cryogenized-spec/SHIORI-/pull/104) is merged, but physical-device acceptance is still outstanding.
3. **Complete everyday task workflows:** durable universal inbox, recurrence, attention and saved views, notifications, calendar-aware scheduling with preview/apply/undo.
4. **Expand the Spatial Workspace and optional AI:** first-class typed artefacts, indexed backlinks, retrieval, validated expressive scenes and a separate secured companion. These are *not prerequisites* for a useful private beta.

[Product roadmap](ROADMAP.md) · [Remote API operation registry](docs/api/operations.v1.json) · [MCP deployment](cloudflare/shiori-mcp/README.md) · [OAuth and sync preview](cloudflare/shiori-mcp/oauth/README.md) · [Android release hold](docs/engineering/M2_5_ANDROID_ACCEPTANCE_AND_RELEASE_HOLD.md)

## Local development (Linux)

Requires the pinned Rust **1.99.1** toolchain. All CLI commands operate on **your local SQLite database**, never the Cloudflare D1 store:

```bash
cargo test --workspace --locked
cargo build --locked -p shiori-cli
target/debug/shiori-cli add "Review the SHIORI roadmap" --project Development --priority high --minutes 45
target/debug/shiori-cli list
target/debug/shiori-cli attention --on 2026-11-18
target/debug/shiori-cli plan 2026-11-18 --start 08:00 --end 17:00 --break-start 13:00 --break-end 14:00 --utc-offset-minutes 120
# Inspect a content-free, read-only identity/revision/tombstone manifest:
target/debug/shiori-cli bridge-manifest
```

Default database: `~/.local/share/shiori/tasks.sqlite3`; specify `--database /path/to/tasks.sqlite3` or `SHIORI_DB`. SQLite v0–v2 files are upgraded transactionally to canonical v3; unknown future schemas are refused. A visual spatial-position sidecar, `tasks.isw.sqlite3`, has its own view revisions; moving a card must not modify task status or dependencies.

### Web UI using real local tasks

The standalone browser prototype uses demo content. To use the **actual** local SQLite tasks:

```bash
cargo build --locked -p shiori-cli
python3 apps/local_bridge.py --cli target/debug/shiori-cli --port 8765
```

Then open `http://127.0.0.1:8765`. The footer identifies **LOCAL RUST / SQLITE**. The `Spatial canvas` link opens the ISW, whose `Live Rust` action reads real tasks and prerequisite relationships. The local attention view reads indexed assigned-to-`local` tasks and explicitly distinguishes blocked work. The planning command remains a **non-mutating fixed-offset preview**, not a DST-aware named-zone or calendar write system.

**Security:** the Python bridge is a *development-only loopback adapter*. Never expose it on a public hostname, LAN, proxy or tunnel; it has no production-grade authentication. [Local bridge threat model](docs/engineering/LOCAL_WEB_BRIDGE.md).

## Remote Cloudflare MCP and OAuth

Shiori's **single-owner** Cloudflare setup consists of `shiori-auth` (OAuth issuer), `shiori-mcp-oauth` (OAuth-protected resource) and a separate `shiori-mcp-alpha` (legacy owner bearer service). Owner approval is operational: ChatGPT has successfully granted `mcp:read` and `mcp:write`, called the live MCP and created remote demo tasks and native dependencies. **Read is mandatory; write is explicitly opt-in.** Tokens and approval codes must never be committed or pasted into issues.

The 124-operation JSON registry is **documentation/discovery**, not 124 runnable tools: **31 implemented and verified deployed**, **93 planned**. The working subset covers task get/list/create/update/status/delete/restore/priority, dependency list/add/remove, spatial scene read/export and position/viewport/layout/inspection, plus capabilities and operation discovery. It now also includes owner-scoped paired-device status and permanent device revocation: import preview/apply reject revoked device IDs inside their D1 transactions. Revocation does not rotate OAuth or legacy bearer credentials. Every mutation requires the appropriate authorization; revisions and idempotency guards are used for supported writes. Production multi-user permissions and sync remain pending.

See [MCP README](cloudflare/shiori-mcp/README.md) for exact active operations, [OAuth README](cloudflare/shiori-mcp/oauth/README.md) for owner grants, and [registry](docs/api/operations.v1.json) for authoritative schemas. Cloudflare D1 is a **separate dataset**; even a matching task title or UUID does not prove it is the same local task.

### Read-only local/cloud comparison

```bash
cargo build --locked -p shiori-cli
python3 cloudflare/shiori-mcp/scripts/sync_preview.py \
  --cli target/debug/shiori-cli --manifest \
  --token-file /path/to/private-owner-bearer-token
```

The script prints **counts only**, obtains remote tasks by authenticated reads, and does **not** send local task records/identifiers or write either database. Use only a private token file; the OAuth approval code is **not** a bearer token. See [ADR 0005](docs/adr/0005-rust-cloudflare-sync.md). Future opt-in synchronization will be separately permissioned, explicitly reviewed, journaled and tested.


**S2/S3 deployment checkpoint:** first-import operations support a single, new revision-1 dependency-free local task after explicit owner pairing, an ID+SHA-256 preview and a separate approval. The user-controlled Python client and original lossless JSON stay outside automatic sync. The read-only S3 `sync.changes.read` API now returns metadata for subsequent task/edge changes and a resumable cutoff. It **does not contain a historical baseline**, and a separate private local read-only pull journal was merged through [PR #70](https://github.com/cryogenized-spec/SHIORI-/pull/70). No background reconciliation or local task modifications are enabled. See [S2 protocol](docs/engineering/RUST_CLOUDFLARE_SYNC_S2.md) and [S3 change-feed guidance](docs/engineering/RUST_CLOUDFLARE_SYNC_S3.md).

## Architecture and scope

- `crates/shiori-core`: pure Rust task/inbox domain and deterministic time-block planning. The inbox currently has **domain rules but not full persistent inbox UX**.
- `crates/shiori-storage`: local SQLite v3 canonical task store, indexes, tombstones and separate spatial view state.
- `apps/shiori-cli`: offline command client and read-only bridge/manifest exports.
- `apps/web`: responsive task board and spatial canvas, demo or optional loopback Rust bridge.
- `apps/android` + `crates/shiori-android-native`: offline Android shell and experimental guarded JNI/SQLite integration; not yet cleared for general release.
- `cloudflare/shiori-mcp`: isolated remote D1 MCP/JSON operation service and OAuth adapter; **not** a replacement for local Rust domain logic.
- `docs/adr`, `docs/engineering`, `ROADMAP.md`: architecture, staged release/acceptance gates and outstanding decisions.

The future architecture makes **Rust application/domain rules authoritative** and treats MCP, HTTP, web and Android as distinct clients, with cloud sync as an optional permissioned adapter. Do not conflate transport success with offline data convergence.

## Quality and release policy

GitHub Actions exercises Rust formatting, strict Clippy, tests, release build, coverage, SQLite performance, RustSec, browser UI, Android host/native cross-target compilation, APK packaging and emulator interaction. A green compilation does **not** replace real phone testing. The [Android emulator touch issue #65](https://github.com/cryogenized-spec/SHIORI-/issues/65) is still open; do not silently disable its assertions. The project is **not yet production beta**.

The [roadmap](ROADMAP.md) distinguishes minimum private-beta features from the larger Spatial/EAI/companion vision. Licensing and contributor/distribution decisions remain open; **AGPLv3 is proposed, not finalized**.

### S2 reviewed first-import pilot

The isolated D1 MCP and local Rust outbox now include a **developer-only** paired-device/first-import protocol (PR #68). It pairs one owner device, previews a digest **without sending title/notes**, and requires a distinct explicit apply command to transfer the complete task. Only new, dependency-free revision-1 tasks are eligible; existing remote tasks/tombstones are never replaced. The initial remote projection keeps a lossless original JSON snapshot and a read-only receipt. This is **not bidirectional sync** and must not be used with production records until CI, D1 migration and synthetic acceptance pass. See [S2 safety guide](docs/engineering/RUST_CLOUDFLARE_SYNC_S2.md).
