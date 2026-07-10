# ucp-server — self-hosted UCP generation service

One process, two interfaces. Point it at GitHub/Jira credentials and get
[Universal Context Packages](https://ucpcore.org) on demand:

- **REST API** (`/v1`) — generate and fetch packages with `curl` or any HTTP client;
- **MCP over Streamable HTTP** (`/mcp`) — plug it straight into Cursor,
  Claude Code, or any MCP-capable agent.

Configuration is environment-only (12-factor), generated packages are cached
on disk with a TTL, and authentication is one env var away. Install it,
start it, forget it.

> PyPI package name: **`ucpcore-server`** (the name `ucp-server` was taken).
> The command it installs is still `ucp-server`.

## Quickstart

### Docker (one command)

```bash
docker run --rm -p 8080:8080 -e GITHUB_TOKEN=ghp_yourtoken \
  ghcr.io/ucpcore/ucp-server:latest
```

### uvx / pipx (no Docker)

```bash
uvx --from ucpcore-server ucp-server
# or: pipx run --spec ucpcore-server ucp-server
```

Then generate a package from any public GitHub issue:

```bash
curl -s -X POST http://localhost:8080/v1/generate \
  -H 'Content-Type: application/json' \
  -d '{"source": "github", "ref": "pallets/flask#5961"}' | head
```

Interactive API docs: <http://localhost:8080/docs>.

### Browser demo (`ucpcore.org/try`)

For the public try page, enable the unauthenticated demo endpoint (GitHub only,
rate-limited, CORS for ucpcore.org):

```bash
docker run --rm -p 8080:8080 \
  -e UCP_DEMO_ENABLED=1 \
  -e GITHUB_TOKEN=ghp_yourtoken \
  ghcr.io/ucpcore/ucp-server:latest
```

```bash
curl -s -X POST http://localhost:8080/v1/demo/generate \
  -H 'Content-Type: application/json' \
  -d '{"ref": "microsoft/vscode#519"}' | jq '.stats'
```

Deploy at `demo.ucpcore.org` and point the try page manifest to that host.

## Connect an agent (MCP)

The MCP endpoint speaks Streamable HTTP at `http://localhost:8080/mcp`.

Cursor / Claude Code (`mcp.json`):

```json
{
  "mcpServers": {
    "ucp": {
      "url": "http://localhost:8080/mcp"
    }
  }
}
```

If the server runs with `UCP_SERVER_API_KEY`, add the header:

```json
{
  "mcpServers": {
    "ucp": {
      "url": "http://localhost:8080/mcp",
      "headers": { "Authorization": "Bearer YOUR_KEY" }
    }
  }
}
```

Tools exposed:

| Tool | Purpose |
|---|---|
| `generate_context(source, ref, llm=False)` | Build a UCP from a GitHub issue (`owner/repo#123`) or Jira ticket (`PROJ-123`) |
| `list_contexts()` | List cached packages: id, entity, title, freshness |
| `get_context(id)` | Full UCP JSON for a cached package |
| `get_context_markdown(id, token_budget?)` | Canonical Markdown rendering (SPEC §7), optionally truncated by salience |

## Chat commands

Once the MCP server is connected, you can drive it from the chat input —
no plugins required.

### MCP prompts (built into the server)

The server exposes two [MCP prompts](https://modelcontextprotocol.io/docs/concepts/prompts)
that clients surface as slash commands automatically:

| Prompt | What it does |
|---|---|
| `ucp_context(ref, llm=false)` | Generate a package for `ref` and use it as the authoritative task context |
| `ucp_catchup(ref)` | Generate a package and brief you: what's decided, what conflicts, what's still open |

The source is detected from the shape of the reference: `owner/repo#123`
is GitHub, `PROJ-123` is Jira.

In **Claude Code** they appear as `/mcp__ucp__ucp_context` and
`/mcp__ucp__ucp_catchup` (assuming the server is named `ucp` in your
config):

```
/mcp__ucp__ucp_context pallets/flask#5961
/mcp__ucp__ucp_catchup PROJ-123
```

In **Cursor** the server's prompts are available to the agent through the
MCP connection; for a first-class `/ucp` command use the file below.

### `/ucp` slash command (copy a file into your project)

Ready-made command files live in [`clients/`](clients/):

```bash
# Cursor
mkdir -p .cursor/commands && cp clients/cursor/ucp.md .cursor/commands/

# Claude Code
mkdir -p .claude/commands && cp clients/claude-code/ucp.md .claude/commands/
```

Then in either client:

```
/ucp pallets/flask#5961
/ucp PROJ-123
```

The command tells the agent to call `generate_context` on the `ucp` MCP
server and treat the returned package as the authoritative task context.

## REST API

| Method & path | Purpose |
|---|---|
| `POST /v1/generate` | Generate a package. Body: `{"source": "github"\|"jira", "ref": "...", "llm": false, "since": null, "audience": null}`. **Requires** `Content-Type: application/json`. Returns the UCP JSON; headers `X-UCP-Package-Id` and `X-UCP-Cache: hit\|miss`. With `since` (ISO timestamp), adds `context_diff` and the `ucp-temporal` profile. |
| `GET /v1/packages` | Cached packages: id, title, entity, generated_at |
| `GET /v1/packages/{id}` | Full UCP JSON |
| `GET /v1/packages/{id}/markdown?token_budget=1500` | Canonical Markdown rendering |
| `GET /healthz`, `GET /readyz` | Liveness / readiness probes (never authenticated) |
| `GET /docs`, `GET /openapi.json` | OpenAPI documentation |

Errors are RFC 9457 problem documents (`application/problem+json`):

```json
{"type": "https://ucpcore.org/problems/invalid-ref", "title": "Invalid Reference",
 "status": 400, "detail": "invalid GitHub reference 'x': expected owner/repo#number..."}
```

Examples:

```bash
# Jira (needs JIRA_* env on the server)
curl -s -X POST http://localhost:8080/v1/generate \
  -H 'Content-Type: application/json' \
  -d '{"source": "jira", "ref": "PROJ-123"}'

# LLM-enhanced (needs UCP_LLM_* env on the server)
curl -s -X POST http://localhost:8080/v1/generate \
  -H 'Content-Type: application/json' \
  -d '{"source": "github", "ref": "microsoft/vscode#519", "llm": true}'

# Catch-up diff since a baseline (adds context_diff + ucp-temporal)
curl -s -X POST http://localhost:8080/v1/generate \
  -H 'Content-Type: application/json' \
  -d '{"source": "github", "ref": "pallets/flask#5961", "since": "2026-01-01T00:00:00Z"}'

# Rendered Markdown under a token budget
curl -s "http://localhost:8080/v1/packages/github-pallets-flask-5961/markdown?token_budget=1500"
```

## Configuration

Everything is optional; the server starts with zero configuration and
reports clearly when a credential is missing for a requested source.

| Variable | Default | Purpose |
|---|---|---|
| `UCP_SERVER_HOST` | `127.0.0.1` (Docker image: `0.0.0.0`) | Bind address |
| `UCP_SERVER_PORT` | `8080` | Bind port |
| `UCP_SERVER_API_KEY` | *(unset — auth disabled)* | Service Bearer key. When set (or when personal tokens exist), endpoints require `Authorization: Bearer …` |

### Personal tokens (alpha.12.1)

Admins create scoped tokens via `POST /v1/admin/tokens` (requires the service API key).
Tokens use the `ctx_` prefix and map **principal** to the token name — personal tokens
ignore the `audience` field on `/v1/generate`.

| Scope | Allows |
|---|---|
| `generate` | `POST /v1/generate`, `GET /v1/packages*`, MCP `/mcp` |
| `receipt` | `POST /v1/receipt` |
| `admin:read` | `GET /v1/admin/*` (except token CRUD) |

Token CRUD and sync triggers require `UCP_SERVER_API_KEY` (service principal).

```bash
# Create a token for a teammate (service key)
curl -s -X POST http://localhost:8080/v1/admin/tokens \
  -H "Authorization: Bearer $UCP_SERVER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"alice","scopes":["generate","receipt"]}'

# Use in Cursor mcp.json
# "headers": { "Authorization": "Bearer ctx_…" }
```

Access by personal tokens is logged to `GET /v1/admin/access-log` (principal = token name).

### Hosted pilot (0.4.0)

For dedicated-tenant deployments set `UCP_TENANT_SLUG`, `UCP_PUBLIC_BASE_URL`, and
`UCP_HOSTED_MODE=1`. Public MCP URL becomes `{base}/v1/{slug}/mcp`. See
[`deploy/pilot/README.md`](../../deploy/pilot/README.md) and Cursor template
[`clients/cursor/ucp-hosted.md`](clients/cursor/ucp-hosted.md).

| Variable | Default | Purpose |
|---|---|---|
| `UCP_TENANT_SLUG` | *(unset)* | Tenant slug in public URLs (`acme-corp`) |
| `UCP_PUBLIC_BASE_URL` | *(unset)* | External base URL for landing + setup JSON |
| `UCP_HOSTED_MODE` | `false` | When true, block legacy `/mcp` and `/v1/*` without slug |
| `UCP_CACHE_DIR` | `~/.cache/ucp-server` | Disk cache for generated packages |
| `UCP_CACHE_TTL` | `900` (15 min) | Cache TTL in seconds; `0` disables caching |
| `UCP_DEMO_ENABLED` | `0` | Enable `POST /v1/demo/generate` (public browser demo) |
| `UCP_DEMO_RATE_LIMIT_PER_HOUR` | `30` | Per-IP rate limit for demo endpoint |
| `UCP_DEMO_CORS_ORIGINS` | `https://ucpcore.org,…` | Allowed browser origins for demo CORS |
| `GITHUB_TOKEN` / `GH_TOKEN` | *(unset)* | GitHub token (public issues work without it, at a low rate limit) |
| `JIRA_BASE_URL` | *(unset)* | e.g. `https://yourcompany.atlassian.net` |
| `JIRA_EMAIL` | *(unset)* | Jira Cloud email (Basic auth); omit for Server/DC PAT |
| `JIRA_API_TOKEN` | *(unset)* | Jira API token or PAT |
| `UCP_LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint for `llm: true` |
| `UCP_LLM_API_KEY` | *(unset)* | LLM API key (falls back to `OPENAI_API_KEY`) |
| `UCP_LLM_MODEL` | `gpt-4o-mini` | LLM model name |
| `UCP_LOG_JSON` | `false` | `1`/`true` switches to JSON-lines logs |
| `UCP_LOG_LEVEL` | `INFO` | Log level |

## Hosted Rangor (multi-tenant pilot)

For **Rangor** hosted stack (`0.5.0-beta`), use tenant-scoped URLs — slug is your
**organization id**, not a global constant:

```text
https://mcp.rangor.io/v1/{tenant_slug}/mcp
https://api.rangor.io/v1/{tenant_slug}/generate
```

Cursor (`mcp.json`):

```json
{
  "mcpServers": {
    "rangor": {
      "url": "https://mcp.rangor.io/v1/acme/mcp"
    }
  }
}
```

Click **Authenticate** in Cursor → portal login at `app.rangor.io`.

Deploy and local dev: [deploy/pilot/README.md](../../deploy/pilot/README.md).  
Cursor hosted guide: [clients/cursor/ucp-hosted.md](clients/cursor/ucp-hosted.md).

### Roles (`UCP_SERVER_ROLE`)

| Role | Use |
|------|-----|
| `full` | Monolith local dev (API + Portal in one process) |
| `api` | `rangor-api` container — REST, MCP, webhooks |
| `portal` | Static SPA only (nginx) |

## Security

- **Set `UCP_SERVER_API_KEY` for any non-localhost deployment.** Without it
  anyone who can reach the port can spend your GitHub/Jira/LLM quota — unless
  you rely solely on personal tokens (`ctx_…`). The service key is compared in
  constant time; health probes and `/admin` login shell stay open.
- **Bind is `127.0.0.1` by default** when run directly. The Docker image
  sets `UCP_SERVER_HOST=0.0.0.0` deliberately — the container boundary is
  the isolation there; publish the port consciously (`-p 127.0.0.1:8080:8080`
  keeps it local).
- **No client-supplied URLs.** Clients pass references (`owner/repo#123`,
  `PROJ-123`) to the two predefined connectors; the server never fetches an
  arbitrary URL on a client's behalf (no SSRF surface).
- Request bodies are limited to 64 KiB and validated strictly (unknown
  fields rejected). Tokens are masked in logs. The Docker image runs as a
  non-root user.

## Development

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Docker image:

```bash
docker build -t ucp-server .
docker run --rm -p 8080:8080 ucp-server
```
