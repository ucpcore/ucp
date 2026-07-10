"""MCP OAuth consent screen (Postman-style approve/cancel)."""
from __future__ import annotations

import html

from .brand import LOGO_SVG, PRODUCT_NAME


def render_mcp_consent_page(
    *,
    client_name: str,
    redirect_uri: str,
    user_email: str,
    user_display_name: str,
    mcp_url: str,
    scopes: list[str],
    consent_id: str,
    approve_url: str,
    cancel_url: str,
) -> str:
    scope_text = ", ".join(scopes) if scopes else "generate, receipt"
    client_label = html.escape(client_name or "MCP Client")
    redirect_safe = html.escape(redirect_uri)
    email_safe = html.escape(user_email)
    name_safe = html.escape(user_display_name)
    mcp_safe = html.escape(mcp_url)
    consent_safe = html.escape(consent_id)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Approve MCP access — {PRODUCT_NAME}</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      background: #f8fafc;
      color: #0f172a;
      display: flex;
      flex-direction: column;
    }}
    .topbar {{
      padding: 1.25rem 2rem;
      border-bottom: 1px solid #e2e8f0;
      background: #fff;
    }}
    .brand {{
      display: flex;
      align-items: center;
      gap: 0.5rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      font-size: 0.95rem;
      color: #334155;
    }}
    .brand-mark {{
      width: 1.5rem;
      height: 1.5rem;
      color: #0f172a;
      display: inline-flex;
    }}
    main {{
      flex: 1;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 2rem 1rem 3rem;
    }}
    .panel {{
      width: min(42rem, 100%);
      text-align: center;
    }}
    h1 {{
      margin: 0 0 0.75rem;
      font-size: 1.65rem;
      font-weight: 700;
      line-height: 1.25;
    }}
    .lead {{
      margin: 0 auto 1.75rem;
      max-width: 34rem;
      color: #475569;
      line-height: 1.55;
      font-size: 0.98rem;
    }}
    .card {{
      text-align: left;
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 0.75rem;
      padding: 1.25rem 1.35rem;
      margin-bottom: 1.5rem;
      box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    }}
    .card h2 {{
      margin: 0 0 1rem;
      font-size: 1rem;
      font-weight: 700;
    }}
    .row {{
      display: grid;
      grid-template-columns: 7.5rem 1fr;
      gap: 0.75rem;
      padding: 0.55rem 0;
      border-top: 1px solid #f1f5f9;
      font-size: 0.92rem;
    }}
    .row:first-of-type {{ border-top: none; padding-top: 0; }}
    .label {{ color: #64748b; font-weight: 600; }}
    .value code {{
      display: block;
      margin-top: 0.15rem;
      padding: 0.45rem 0.55rem;
      border-radius: 0.4rem;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      font-size: 0.82rem;
      word-break: break-all;
      white-space: pre-wrap;
    }}
    .actions {{
      display: flex;
      justify-content: flex-end;
      gap: 0.75rem;
      flex-wrap: wrap;
    }}
    .btn {{
      appearance: none;
      border: none;
      border-radius: 0.45rem;
      padding: 0.65rem 1.15rem;
      font-size: 0.92rem;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
    }}
    .btn-cancel {{
      background: #fff;
      color: #334155;
      border: 1px solid #cbd5e1;
    }}
    .btn-cancel:hover {{ background: #f8fafc; }}
    .btn-approve {{
      background: #2563eb;
      color: #fff;
    }}
    .btn-approve:hover {{ background: #1d4ed8; }}
    .signed-in {{
      margin-top: 1.25rem;
      font-size: 0.82rem;
      color: #64748b;
    }}
  </style>
</head>
<body>
  <header class="topbar">
    <div class="brand"><span class="brand-mark" aria-hidden="true">{LOGO_SVG}</span> {PRODUCT_NAME.upper()}</div>
  </header>
  <main>
    <div class="panel">
      <h1>Approve Client Authorization via {PRODUCT_NAME} MCP</h1>
      <p class="lead">
        <strong>{client_label}</strong> is requesting authorization to access and act upon
        resources on your behalf via the {PRODUCT_NAME} MCP server.
        Approving this request will redirect you back to the client.
      </p>
      <div class="card">
        <h2>Client Details</h2>
        <div class="row">
          <div class="label">Name</div>
          <div class="value">{client_label}</div>
        </div>
        <div class="row">
          <div class="label">Redirect URI</div>
          <div class="value"><code>{redirect_safe}</code></div>
        </div>
        <div class="row">
          <div class="label">MCP endpoint</div>
          <div class="value"><code>{mcp_safe}</code></div>
        </div>
        <div class="row">
          <div class="label">Scopes</div>
          <div class="value">{html.escape(scope_text)}</div>
        </div>
      </div>
      <div class="actions">
        <a class="btn btn-cancel" href="{html.escape(cancel_url)}">Cancel</a>
        <form method="post" action="{html.escape(approve_url)}" style="margin:0">
          <input type="hidden" name="consent_id" value="{consent_safe}"/>
          <button class="btn btn-approve" type="submit">Approve</button>
        </form>
      </div>
      <p class="signed-in">Signed in as <strong>{name_safe}</strong> ({email_safe})</p>
    </div>
  </main>
</body>
</html>"""


def render_mcp_consent_cancelled(*, client_name: str) -> str:
    client_label = html.escape(client_name or "MCP Client")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Authorization cancelled — {PRODUCT_NAME}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: system-ui, sans-serif;
      background: #f8fafc;
      color: #0f172a;
      padding: 2rem;
      text-align: center;
    }}
    .box {{
      max-width: 28rem;
      background: #fff;
      border: 1px solid #e2e8f0;
      border-radius: 0.75rem;
      padding: 1.5rem;
    }}
    h1 {{ margin: 0 0 0.75rem; font-size: 1.25rem; }}
    p {{ margin: 0; color: #475569; line-height: 1.5; }}
  </style>
</head>
<body>
  <div class="box">
    <h1>Authorization cancelled</h1>
    <p>You declined access for <strong>{client_label}</strong>. You can close this tab and return to Cursor.</p>
  </div>
</body>
</html>"""
