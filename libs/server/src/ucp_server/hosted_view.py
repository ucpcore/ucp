"""Hosted pilot onboarding page and setup JSON (RFC-0009)."""
from __future__ import annotations

import json
from typing import Any

from .tenant import public_api_url, public_mcp_url


def display_host_hint(host: str, port: int) -> str:
    """Human-facing host — 0.0.0.0 is bind-all, not reachable in browsers."""
    bind = host.strip() or "127.0.0.1"
    if bind in {"0.0.0.0", "::", "[::]"}:
        bind = "127.0.0.1"
    return f"{bind}:{port}"



def build_client_configs(mcp_url: str) -> dict[str, Any]:
    """Per-client MCP connection snippets (OAuth-first, manual token fallback)."""
    headers = {"Authorization": "Bearer ${env:UCP_CTX_TOKEN}"}
    manual_note = (
        "Fallback: export UCP_CTX_TOKEN=ctx_… from /dashboard/access, then use this config."
    )

    return {
        "cursor": {
            "label": "Cursor",
            "config_path": "Settings → MCP, or ~/.cursor/mcp.json",
            "auth_mode": "oauth",
            "note": "Settings → MCP → contextos → Authenticate.",
            "config": {"mcpServers": {"contextos": {"url": mcp_url}}},
            "fallback_config": {
                "mcpServers": {"contextos": {"url": mcp_url, "headers": headers}}
            },
            "fallback_note": manual_note,
        },
        "claude_code": {
            "label": "Claude Code",
            "config_path": "~/.claude.json, project .mcp.json, or `claude mcp add --transport http`",
            "auth_mode": "oauth",
            "note": "Run `/mcp` → Authenticate, or `claude mcp login contextos` after adding the server.",
            "config": {
                "mcpServers": {
                    "contextos": {"type": "http", "url": mcp_url},
                }
            },
            "fallback_config": {
                "mcpServers": {
                    "contextos": {
                        "type": "http",
                        "url": mcp_url,
                        "headers": headers,
                    }
                }
            },
            "fallback_note": manual_note,
        },
        "vscode": {
            "label": "VS Code",
            "config_path": ".vscode/mcp.json (GitHub Copilot MCP)",
            "auth_mode": "oauth",
            "note": "Copilot Chat → MCP → contextos → Sign in / Authenticate.",
            "config": {
                "servers": {
                    "contextos": {"type": "http", "url": mcp_url},
                }
            },
            "fallback_config": {
                "servers": {
                    "contextos": {
                        "type": "http",
                        "url": mcp_url,
                        "headers": headers,
                    }
                }
            },
            "fallback_note": manual_note,
        },
        "windsurf": {
            "label": "Windsurf",
            "config_path": "~/.codeium/windsurf/mcp_config.json",
            "auth_mode": "oauth",
            "note": "If Authenticate is available, use URL-only config. Otherwise use manual token fallback.",
            "config": {"mcpServers": {"contextos": {"url": mcp_url}}},
            "fallback_config": {
                "mcpServers": {"contextos": {"url": mcp_url, "headers": headers}}
            },
            "fallback_note": manual_note,
        },
        "claude_desktop": {
            "label": "Claude Desktop",
            "config_path": "~/Library/Application Support/Claude/claude_desktop_config.json",
            "auth_mode": "manual",
            "warning": (
                "Claude Desktop supports stdio only — no browser OAuth. "
                "Use mcp-remote with UCP_CTX_TOKEN from API Access."
            ),
            "note": "export UCP_CTX_TOKEN=ctx_… then reload Claude Desktop MCP.",
            "config": {
                "mcpServers": {
                    "contextos": {
                        "command": "npx",
                        "args": [
                            "-y",
                            "mcp-remote",
                            mcp_url,
                            "--header",
                            "Authorization: Bearer ${env:UCP_CTX_TOKEN}",
                        ],
                    }
                }
            },
        },
    }


def _setup_common(*, mcp_url: str, admin_url: str, version: str, **extra: Any) -> dict[str, Any]:
    client_configs = build_client_configs(mcp_url)
    return {
        "version": version,
        "mcp_url": mcp_url,
        "admin_url": admin_url,
        "client_configs": client_configs,
        # Back-compat alias for older consumers
        "cursor_config": client_configs["cursor"]["config"],
        "onboarding": [
            "OAuth (recommended): paste URL-only config, then Authenticate in Cursor, Claude Code, or VS Code.",
            "Manual fallback: export UCP_CTX_TOKEN=ctx_… from /dashboard/access — see each client's fallback tab.",
            "Claude Desktop: mcp-remote bridge only (no OAuth).",
        ],
        **extra,
    }


def build_setup_payload(
    *,
    tenant_slug: str,
    public_base_url: str,
    version: str,
) -> dict[str, Any]:
    mcp_url = public_mcp_url(public_base_url, tenant_slug)
    admin_url = public_api_url(public_base_url, tenant_slug, "/admin")
    return _setup_common(
        mcp_url=mcp_url,
        admin_url=admin_url,
        version=version,
        tenant_slug=tenant_slug,
        public_base_url=public_base_url.rstrip("/"),
        api_base=f"/v1/{tenant_slug}",
    )


def render_hosted_landing(*, tenant_slug: str, public_base_url: str, version: str) -> str:
    setup = build_setup_payload(
        tenant_slug=tenant_slug,
        public_base_url=public_base_url,
        version=version,
    )
    mcp_url = setup["mcp_url"]
    admin_url = setup["admin_url"]
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Context OS — MCP Hosted</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 42rem; line-height: 1.5;
      background: #0f172a; color: #e2e8f0; padding: 0 1rem; }}
    h1 {{ margin-bottom: 0.25rem; }}
    .meta {{ color: #94a3b8; }}
    code, pre {{ background: #1e293b; padding: 0.15rem 0.35rem; border-radius: 4px; }}
    pre {{ padding: 1rem; overflow-x: auto; }}
    a {{ color: #60a5fa; }}
    ol {{ padding-left: 1.25rem; }}
    .badge {{ display: inline-block; background: #1e3a5f; color: #93c5fd; padding: 0.15rem 0.5rem;
      border-radius: 4px; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <p class="badge">Hosted pilot · v{version}</p>
  <h1>Context OS MCP</h1>
  <p class="meta">Tenant <code>{tenant_slug}</code> · dedicated stack (RFC-0009)</p>

  <h2>MCP URL</h2>
  <pre id="mcp-url">{mcp_url}</pre>

  <p class="meta">Client configs: <a href="/dashboard/setup">MCP Setup</a> in portal</p>

  <h2>Onboarding</h2>
  <ol>
    <li>Personal token: <a href="/dashboard/access">API Access</a> (or admin: <a href="{admin_url}">{admin_url}</a>)</li>
    <li>Copy URL and <code>ctx_…</code> into your MCP client — see <a href="/dashboard/setup">MCP Setup</a></li>
    <li>In chat: <code>/ucp PAY-123</code> or <code>/ucp owner/repo#42</code></li>
  </ol>

    <p class="meta">Setup JSON: <a href="/setup">/setup</a> · Dashboard: <a href="/dashboard">/dashboard</a> · Spec: <a href="https://ucpcore.org">ucpcore.org</a></p>
</body>
</html>"""


def render_local_landing(*, version: str, host_hint: str = "127.0.0.1:8080") -> str:
    """Self-hosted landing when UCP_TENANT_SLUG is not configured."""
    mcp_url = f"http://{host_hint}/mcp"
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Context OS — MCP</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 42rem; line-height: 1.5;
      background: #0f172a; color: #e2e8f0; padding: 0 1rem; }}
    h1 {{ margin-bottom: 0.25rem; }}
    .meta {{ color: #94a3b8; }}
    code {{ background: #1e293b; padding: 0.15rem 0.35rem; border-radius: 4px; }}
    a {{ color: #60a5fa; }}
    ul {{ padding-left: 1.25rem; }}
  </style>
</head>
<body>
  <h1>Context OS MCP</h1>
  <p class="meta">Self-hosted · v{version}</p>
  <ul>
    <li>MCP endpoint: <code>{mcp_url}</code></li>
    <li><a href="/admin">Admin</a> · <a href="/dashboard">Dashboard</a> · <a href="/dashboard/setup">MCP Setup</a></li>
  </ul>
  <p class="meta">Hosted pilot: set <code>UCP_TENANT_SLUG</code> + <code>UCP_PUBLIC_BASE_URL</code> for tenant URLs.</p>
</body>
</html>"""


def build_local_setup(*, version: str, host_hint: str = "127.0.0.1:8080") -> dict[str, Any]:
    base = f"http://{host_hint}"
    return _setup_common(
        mcp_url=f"{base}/mcp",
        admin_url=f"{base}/admin",
        version=version,
        mode="self-hosted",
        portal_url=f"{base}/dashboard",
        api_base="/v1",
    )


def _render_client_sections(client_configs: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("cursor", "claude_code", "vscode", "windsurf", "claude_desktop"):
        entry = client_configs.get(key)
        if not entry:
            continue
        label = entry.get("label", key)
        path = entry.get("config_path", "")
        cfg_json = json.dumps(entry.get("config") or {}, indent=2, ensure_ascii=False)
        warn = entry.get("warning")
        warn_html = f'<p class="warn meta">{warn}</p>' if warn else ""
        open_attr = ' open' if key == "cursor" else ""
        parts.append(
            f"<details{open_attr}><summary><strong>{label}</strong>"
            f' — <span class="meta">{path}</span></summary>'
            f"{warn_html}<pre>{cfg_json}</pre></details>"
        )
    return "\n".join(parts)


def render_setup_html(payload: dict[str, Any]) -> str:
    """Browser setup page at GET /setup (not /mcp — that path is the MCP protocol)."""
    mcp_url = payload.get("mcp_url", "")
    admin_url = payload.get("admin_url", "")
    access_url = payload.get("access_url") or payload.get("portal_url", "/dashboard/access")
    client_configs = payload.get("client_configs") or build_client_configs(mcp_url)
    client_sections = _render_client_sections(client_configs)
    tenant = payload.get("tenant_slug")
    tenant_line = (
        f'<p class="meta">Tenant <code>{tenant}</code></p>' if tenant else ""
    )
    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Context OS — MCP Setup</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 42rem; line-height: 1.5;
      background: #0f172a; color: #e2e8f0; padding: 0 1rem; }}
    h1 {{ margin-bottom: 0.25rem; font-size: 1.25rem; }}
    .meta {{ color: #94a3b8; font-size: 0.875rem; }}
    code, pre {{ background: #1e293b; padding: 0.15rem 0.35rem; border-radius: 4px; }}
    pre {{ padding: 0.75rem; overflow-x: auto; font-size: 0.8rem; }}
    a {{ color: #60a5fa; }}
    .note, .warn {{ border-left: 3px solid #334155; padding-left: 0.75rem; margin: 0.75rem 0; }}
    .warn {{ border-color: #b45309; }}
    details {{ margin: 0.75rem 0; border: 1px solid #334155; border-radius: 6px; padding: 0.5rem 0.75rem; }}
    summary {{ cursor: pointer; }}
    details pre {{ margin-top: 0.5rem; }}
  </style>
</head>
<body>
  <p><a href="/">← Home</a> · <a href="/dashboard">Dashboard</a> · <a href="{access_url}">API Access</a></p>
  <h1>MCP Setup</h1>
  <p class="meta">Страница настройки. Endpoint для агентов — ниже (это не URL этой страницы).</p>
  {tenant_line}
  <p class="note meta"><strong>/mcp</strong> — протокол MCP (Streamable HTTP). Сюда подключаются клиенты, не браузер.</p>
  <h2>MCP endpoint URL</h2>
  <pre>{mcp_url}</pre>
  <p class="meta">Personal token: <a href="{access_url}">{access_url}</a> · замените <code>ctx_YOUR_TOKEN</code> в конфигах ниже.</p>
  <h2>Клиенты</h2>
  {client_sections}
  <p class="meta">JSON: <a href="/setup?format=json">/setup?format=json</a>
  · Admin: <a href="{admin_url}">{admin_url}</a></p>
</body>
</html>"""
