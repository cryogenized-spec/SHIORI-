# SHIORI S8 — Explicit, backed-up single-task cloud-to-Rust apply

**Alpha, 19 November 2026.** This is the first intentionally **content-bearing, owner-invoked local apply path**. It is not an automatic background agent, remote-to-local full schema replication or continuous two-device synchronization.

This workflow **does write canonical Rust task data when and only when its second phase is explicitly approved**. Never invoke it against production tasks as a casual test. Use a disposable S2-imported task first, verify the resulting local backup and task revision, and retain the backup until the state is audited. It never writes to Cloudflare.

## Preconditions

- A canonical Rust SQLite v3 task exists, is active, and has a previously **acknowledged original S2 first-import** in the private journal.
- A private \`.pull-preview.sqlite3\` file already holds an explicit owner-selected S4 snapshot for that very task.
- All four inputs (Rust DB, preview, S2 journal, owner token file) are existing regular private 0600 files; no symlinks, hardlink aliases or insecure files. The CLI binary and backup destination are local to a trusted workstation.
- The owner has inspected the selected cloud record's title, notes, project, priority and status in a trusted SHIORI view **before approving**. Only five common fields are eligible.
- The local task's five common fields must still exactly match the original S2 source. If a different offline device or local editing changed one of these fields, **stop for manual three-way conflict resolution** rather than overwrite it. Local-only due dates, effort estimates, assignees and completion semantics remain Rust-owned.
- The local dependency graph must equal the staged and live remote graph. Tombstones and missing canonical/source records are refused.

## Phase 1 — Fresh owner-authenticated review; no writes

Run the following with the desired *original* task and event IDs (do not share token content or private task files):

\`\`\`bash
python3 cloudflare/shiori-mcp/scripts/sync_apply_owner.py \
  --canonical "$HOME/.local/share/shiori/tasks.sqlite3" \
  --outbox "$HOME/.local/share/shiori/tasks.sync.sqlite3" \
  --shadow "$HOME/.local/share/shiori/remote.pull-preview.sqlite3" \
  --token-file "$HOME/.local/share/shiori/owner-token" \
  --task-id '<ORIGINAL-TASK-UUID>' \
  --event-id 'sync1:<DEVICE-UUID>:<ORIGINAL-TASK-UUID>:1' \
  --confirm-read-content
\`\`\`

It checks original S2 acknowledgement, exact S4 staged-record hash, local source/common fields and dependencies, then makes **two owner-authenticated HTTPS reads**: the original import receipt and an atomic current remote S4 task observation. It requires the fresh observation to match the private staging hash, original receipt identity, current remote revision and graph. The stdout report contains revision numbers, mismatch counts and the SHA-256 of the selected remote observation, **never titles or notes**. A changed cloud revision requires a newly staged preview and another review.

The SHA-256 printed as \`remote_observation_sha256_to_approve\` is the **exact observed record to approve**, not a capability token or a substitute for inspecting its content. Do not approve a hash just because it appears in a report.

## Phase 2 — One reviewed local apply

After inspecting the cloud task and verifying phase 1, run the same command with these additional options:

\`\`\`bash
  --approve-digest '<REVIEWED_REMOTE_OBSERVATION_SHA256>' \
  --confirm-apply \
  --backup-to "$HOME/.local/share/shiori/pre-apply-unique.shiori-backup.sqlite3" \
  --cli /trusted/path/to/shiori
\`\`\`

The owner CLI call uses JSON supplied **only through stdin**, never through process arguments or its success output. It rechecks the specific local task's expected revision and prerequisites. It creates a new private, verified SQLite backup via the already merged S7 \`VACUUM INTO\` implementation before it attempts the one-task conditional CAS update. The final Rust store method preserves local-only fields and bumps revision once. An existing backup path, missing approval, unsafe input or changed version/graph fails closed. The Python orchestrator reads the local task back to confirm the five agreed fields and expected revision. Its report does not assert \`automatic_sync=true\` or mutate Cloudflare.

**Crash/retry semantics:** if the local CLI times out, is interrupted after commit, or post-apply verification is inconclusive, the outcome is *unknown*, not proven false. Inspect the local task revision and preserved pre-apply backup **before any retry**. Never reuse an existing backup filename. Rollback remains a separate future recovery workflow; the program will not silently revert possibly newer offline edits.

**Important limit:** cloud state is only proven as of the last authenticated read. A remote edit immediately after that read cannot be prevented by this one-way local operation; the next S4/S6 reconciliation must discover it. The local and remote revision numbers are unrelated and no durable bidirectional revision map or physical two-device convergence has been implemented. Neither the Python script nor this development CLI is exposed to untrusted clients. The hidden Rust CLI is a local mutation primitive and **does not independently authenticate Cloudflare**; it must be invoked only by the verified Python owner workflow. It is not a public service or REST/MCP write route.

## Validation

\`\`\`bash
python3 -m unittest discover -s tests -p 'test_sync_apply_owner.py' -v
cargo test -p shiori-cli
cargo fmt --all -- --check
cargo clippy --workspace --all-targets -- -D warnings
\`\`\`

The tests exercise synthetic original S2 receipt and S4 content, owner approval/digest mismatch, simultaneous local offline edits, remote content changes, tombstones, dependency differences, missing/unsafe inputs, existing backup, post-apply uncertainty and Rust single-revision CAS/backup. **No real account or task data is touched by CI.**

Outstanding milestones: privileged owner identity/approval UI, a durable checked local/remote revision map, conflict-resolution UI, explicit restore, and physical offline two-device convergence. S8 is a manual sync bridge, not the completed automatic sync roadmap.
