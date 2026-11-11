---
name: shiori-rust-mcp
description: Implement, review and test SHIORI's portable Rust MCP server, typed tools, authentication, scoped permissions, audit trail and optional MCP Apps task cards. Use whenever adding or modifying MCP tools, transports, protocol versions, agent integrations, or model-facing task operations.
---

# SHIORI MCP integration

MCP is an optional capability adapter—not SHIORI's database and not the source of business rules. Read `ROADMAP.md` and relevant architecture/security ADRs.

## Implementation workflow

1. Check current official protocol specification at https://modelcontextprotocol.io/specification and official Rust SDK at https://github.com/modelcontextprotocol/rust-sdk before adding dependencies or implementing protocol behaviors. Do not reuse stale SDK templates or hard-coded old crate versions.
2. Keep MCP handlers thin. Delegate to the shared task application/domain layer used by CLI, native UI and REST.
3. Give each operation a distinct, typed name, JSON schema, explicit input validation and clear structured output. Avoid catch-all tools that dynamically choose actions.
4. Authorize reads and writes server-side per identity, workspace, resource and scope. Session IDs are not authentication. Reject unauthorized cross-workspace identifiers.
5. Destructive or bulk operations require appropriate confirmation, idempotency strategy and audit trail. Agents must not silently delete, overwrite or reschedule large groups of tasks.
6. Avoid exporting credentials, private user content and tasks into logs or third-party systems. Use least-privilege tokens and secure secret storage; do not hard-code secrets.
7. Keep STDIO local usage and network-exposed transport threat models distinct. Apply appropriate OAuth/audience checks and rate limits for remote access.
8. Optional compact MCP Apps UI resources must be versioned and degrade gracefully to plain text/structured results in clients without UI support.

## Verification

Test schema validation, unknown parameters, authentication bypass/IDOR attempts, permission boundaries, duplicate writes, cancellation, reconnect, pagination, error contracts, client negotiation and protocol conformance. Cross-check current SDK documentation; do not claim support until tests show it.
