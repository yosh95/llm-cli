# MCP Zero-Trust Security Configuration Examples

This document provides **recommended** security configuration examples for `llm-cli` when operating in **MCP-mediated execution mode**.

## 1) Least-privilege roles per MCP server (recommended)

Define roles per server in your config (example shown in TOML-ish structure; adapt to your actual `config.toml` layout):

```toml
[[mcp_servers]]
name = "github"
command = "docker"
args = ["run", "--rm", "-i", "ghcr.io/github/github-mcp-server:latest"]
# Least privilege: repo read-only
roles = ["guest"]

[[mcp_servers]]
name = "ops"
command = "ssh"
args = ["user@host", "python3", "-m", "llm_cli.apps.mcp_server"]
# Allow safe operational tasks
roles = ["user"]
```

### Environment override (optional)

You can override roles using `MCP_ROLES` (CSV):

```bash
export MCP_ROLES="guest"
```

Notes:
- **Do not** default to `admin` for remote servers.
- Prefer distinct roles per server namespace.

## 2) Recommended intent-analyzer failure policy

For **high-risk** tools, recommended default is **fail-closed** when the intent analyzer is unavailable.

Example security config:

```toml
[security]
intent_analyzer_enabled = true
intent_analyzer_provider = "google"
intent_analyzer_model = "gemini-flash-lite-latest"

# If analyzer init/call fails:
intent_analyzer_fail_open = false

# Allow fail-open only for low-risk read tools (example)
intent_analyzer_fail_open_tools = ["read_file", "list_files"]

# Enforce fail-closed explicitly for high-risk tools (example)
intent_analyzer_fail_closed_tools = ["execute_command", "edit_file", "write_file", "delete_file"]
```

## 3) Trust boundary / TCB assumptions (MCP)

When `llm-cli` launches an MCP server process (local, Docker, or SSH), the **server binary/container image and its launch configuration** are part of the **Trusted Computing Base (TCB)**.

Recommendations:
- Pin Docker image digests where possible.
- Use `ssh` host key verification.
- Treat `config.toml` as sensitive; restrict write access.

## 4) Path scope semantics

Path scopes should be written to match **normalized absolute paths** where practical.

Example:

```toml
[security.roles.user.scopes.edit_file]
allowed_paths = ["./*", "./docs/*"]
```

`llm-cli` normalizes/expands user paths before enforcement to reduce bypass via `..` or symlinks.

## 5) Audit log retention and integrity

`llm-cli` uses a chained-hash JSONL audit log for tamper evidence. To avoid breaking the chain when the log exceeds a maximum size, it rotates overflow lines into an archive file and inserts a snapshot anchor entry in the remaining log.

Recommendations:
- Back up `audit.jsonl` and its `*.archive.*.jsonl` files.
- Forward logs to a remote WORM store (SIEM) if available.
