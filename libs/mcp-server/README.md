# ucp-mcp — reference MCP server for Universal Context Packages

Exposes UCP documents to any MCP-capable agent (Cursor, Claude Code, Codex,
Gemini CLI, …). This is the reference composition of the two protocols:

> **MCP is the pipe. UCP is what flows through it.**

The server watches a directory of `*.ucp.json` files and serves them through
three tools. Any producer (a context platform, a script, a CI job) can drop
packages into that directory; any agent connected to the server can consume
task context that is structured, provenance-backed, and token-budgeted.

## Install & run

```bash
pip install ucp-mcp
ucp-mcp --dir ./contexts        # or: UCP_DIR=./contexts ucp-mcp
```

Cursor / Claude Code configuration (`mcp.json`):

```json
{
  "mcpServers": {
    "ucp": {
      "command": "ucp-mcp",
      "args": ["--dir", "/path/to/contexts"]
    }
  }
}
```

## Tools

| Tool | Purpose |
|---|---|
| `list_contexts()` | Inventory: entity id, title, system, freshness for every available package |
| `get_context(entity)` | Full UCP JSON for an entity (by id, URL, or title fragment) |
| `get_context_markdown(entity, token_budget?)` | Canonical CommonMark rendering (SPEC §7), optionally truncated to a token budget by salience |

`entity` matching is forgiving: exact entity id (`PAY-482`), source URL, or a
case-insensitive title fragment.

## Why a directory of files?

This server is a *reference*, not a product. Its job is to demonstrate the
MCP+UCP composition end to end with zero infrastructure, so that:

- agent users can try UCP in one minute;
- producers see the contract they need to implement (a real producer replaces
  the directory with a live Context Builder, keeping the same tools).

## Development

```bash
pip install -e ".[dev]"
pytest
```
