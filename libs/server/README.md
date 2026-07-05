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

## REST API

| Method & path | Purpose |
|---|---|
| `POST /v1/generate` | Generate a package. Body: `{"source": "github"\|"jira", "ref": "...", "llm": false, "since": null, "audience": null}`. Returns the UCP JSON; headers `X-UCP-Package-Id` and `X-UCP-Cache: hit\|miss`. |
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
| `UCP_SERVER_API_KEY` | *(unset — auth disabled)* | When set, all endpoints except health probes require `Authorization: Bearer <key>` |
| `UCP_CACHE_DIR` | `~/.cache/ucp-server` | Disk cache for generated packages |
| `UCP_CACHE_TTL` | `900` (15 min) | Cache TTL in seconds; `0` disables caching |
| `GITHUB_TOKEN` / `GH_TOKEN` | *(unset)* | GitHub token (public issues work without it, at a low rate limit) |
| `JIRA_BASE_URL` | *(unset)* | e.g. `https://yourcompany.atlassian.net` |
| `JIRA_EMAIL` | *(unset)* | Jira Cloud email (Basic auth); omit for Server/DC PAT |
| `JIRA_API_TOKEN` | *(unset)* | Jira API token or PAT |
| `UCP_LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI-compatible endpoint for `llm: true` |
| `UCP_LLM_API_KEY` | *(unset)* | LLM API key (falls back to `OPENAI_API_KEY`) |
| `UCP_LLM_MODEL` | `gpt-4o-mini` | LLM model name |
| `UCP_LOG_JSON` | `false` | `1`/`true` switches to JSON-lines logs |
| `UCP_LOG_LEVEL` | `INFO` | Log level |

## Security

- **Set `UCP_SERVER_API_KEY` for any non-localhost deployment.** Without it
  anyone who can reach the port can spend your GitHub/Jira/LLM quota. The
  key is compared in constant time; health probes stay open for orchestrators.
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
