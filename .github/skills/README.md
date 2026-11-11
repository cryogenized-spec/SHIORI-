# SHIORI agent skills — maintained catalog

Skills live under `.github/skills/<name>/SKILL.md`, which GitHub Copilot supports for repository-local agent skills. Skills are **guidance**, not installed executables or a substitute for tests. Use only those relevant to a task.

## Imported, verbatim under MIT licence

Upstream: https://github.com/github/awesome-copilot  
Pinned upstream commit: `eaaffd5d020b756a2777a4b1b161d2bdc126d9a0` (2026-11-11 snapshot)  
Licence: MIT, copied at `docs/third-party/github-awesome-copilot-LICENSE.txt`.

| Skill | When to use | Caveat |
|---|---|---|
| `security-review` | Review application security, vulnerable data flows and secrets | Includes all five referenced guidance documents; report findings with evidence |
| `github-actions-hardening` | Review workflows, permissions, triggers and action pinning | Includes its five reference documents; examples need repo-specific verification |
| `playwright-generate-test` | Turn observed browser scenarios into reproducible tests | Requires suitable browser/Playwright tools; does not run automatically merely because installed |
| `agent-supply-chain` | Review agent tool/plugin integrity and dependency provenance | Hash manifests support integrity checks but do **not** prove a publisher's identity |

The imported text is preserved, not automatically executed. To update, diff each upstream `SKILL.md` and its referenced files, inspect any executable resources, confirm licence, and refresh this pinned revision only after review. No background skill auto-updates.

## SHIORI-authored skills

| Skill | When to use |
|---|---|
| `shiori-rust-architecture` | Rust core, storage, CLI and performance changes |
| `shiori-offline-data-integrity` | Sync, SQLite, deletion, migrations, backup/restore |
| `shiori-rust-mcp` | Typed MCP tools, SDK, auth and compact task UI |
| `shiori-visual-system` | Desktop/mobile UI, calendar, colour, art and accessibility |

## Deliberately not imported

- `pedronauck/skills/rust-best-practices`: previously suggested path could not be verified.
- `github/awesome-copilot/rust-mcp-server-generator`: currently contains older Rust/SDK templates and `Cargo.lock` ignore guidance conflicting with this project; use `shiori-rust-mcp` instead.
- `anthropics/skills/skill-creator`: verified as Apache-2.0, but this comparatively large, Claude-oriented package was not needed to begin SHIORI's skills collection. Could add later with its own licence and dependency review.

## Automatic discovery

GitHub Copilot and supported tools discover these skill files from `.github/skills/` and decide when the descriptions match a task. **Plain ChatGPT chats or GitHub connector access do not automatically load repository skills.** When reviewing or working on GitHub, inspect relevant skill instructions explicitly if your agent does not auto-discover them.

## Validation

CI checks the repository skills' frontmatter, names and presence of referenced documents. The checks do not establish that an AI model actually invoked a skill or that its advice is complete.
