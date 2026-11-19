# SHIORI — Rust common-field apply primitive (pre-release)

This is an **opt-in, local Rust storage primitive**, not a synchronization command and not a deployed Android task write. It is a building block for a future authenticated, owner-approved cloud-to-canonical write-back.

The domain method `Task::apply_reviewed_remote_common_fields` validates title, project, notes (maximum 8,192 Unicode characters), priority and task status, and increments the local revision **once** if any of the common fields change. If the status changes to or from Done, it preserves existing Rust completion timestamp rules. An identical record is a no-op.

The storage method `SqliteStore::apply_remote_common_fields_if_version` additionally requires an explicit approval boolean, an existing active local task with matching expected local revision, and a conditional SQLite update that refuses stale writers. Existing due dates, effort estimates, assignees, created timestamps, stable IDs and task dependencies are untouched. A deleted task cannot be silently reanimated.

**The method does not itself authenticate device identity, verify an S2 first-import receipt, validate an S4 remote observation hash, fetch cloud content, create the user's backup or persist a last-synchronized remote revision.** The user-facing orchestrator must perform each of those before invoking it, and must never assume local revision equals remote revision. This method is deliberately not wired to any CLI, REST, Android UI or MCP automatic sync path yet; therefore adding it cannot mutate current user data.

Core and storage unit tests verify single-increment updates, no-op idempotence, local-only field preservation, invalid input rejection, stale local revisions, missing approval and deleted task protection.

Subsequent release steps: add an authenticated S4 snapshot-to-Rust command using only an S2-verified identity, full offline backup/rollback, local/remote revision mapping, independent audit receipt, and two-device actual offline convergence. Until all gates pass, `local_rust_sync=false` stays accurate.
