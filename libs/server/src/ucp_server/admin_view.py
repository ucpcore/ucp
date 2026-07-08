"""Minimal Admin Dashboard HTML (browser login + client-side fetch)."""
from __future__ import annotations


def render_admin_app() -> str:
    """Self-contained admin UI: API key in sessionStorage, data via /v1/admin/sources."""
    return """<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Context OS — Admin</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; background: #0f172a; color: #e2e8f0; }
    h1 { margin-bottom: 0.25rem; }
    .meta { color: #94a3b8; margin-bottom: 1.5rem; }
    .login { max-width: 28rem; margin: 4rem auto; padding: 1.5rem; background: #1e293b; border-radius: 8px; }
    .login input { width: 100%; box-sizing: border-box; padding: 0.5rem; margin: 0.5rem 0 1rem; border: 1px solid #334155; border-radius: 4px; background: #0f172a; color: #e2e8f0; }
    .login button, .toolbar button { padding: 0.5rem 1rem; background: #2563eb; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
    .login button:hover, .toolbar button:hover { background: #1d4ed8; }
    .error { color: #f87171; margin-top: 0.5rem; }
    table { border-collapse: collapse; width: 100%; margin-bottom: 2rem; }
    th, td { border: 1px solid #334155; padding: 0.5rem 0.75rem; text-align: left; }
    th { background: #1e293b; }
    tr:nth-child(even) { background: #1e293b55; }
    .ok { color: #16a34a; font-weight: 600; }
    .pending { color: #ca8a04; font-weight: 600; }
    .disabled { color: #94a3b8; font-weight: 600; }
    .hidden { display: none; }
    .toolbar { margin-bottom: 1rem; display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: center; }
    .sync-btn { padding: 0.25rem 0.5rem; font-size: 0.85rem; background: #334155; }
    .sync-btn:hover { background: #475569; }
    .toast { color: #86efac; margin-left: 0.5rem; font-size: 0.9rem; }
  </style>
</head>
<body>
  <div id="login-view" class="login">
    <h1>Context OS Admin</h1>
    <p class="meta">Введите <code>UCP_SERVER_API_KEY</code> для доступа к health коннекторов.</p>
    <label for="api-key">API key</label>
    <input id="api-key" type="password" autocomplete="off" placeholder="Bearer token"/>
    <button type="button" id="login-btn">Войти</button>
    <p id="login-error" class="error hidden"></p>
  </div>

  <div id="dashboard-view" class="hidden">
    <div class="toolbar">
      <button type="button" id="refresh-btn">Обновить</button>
      <button type="button" id="logout-btn">Выйти</button>
      <span id="sync-toast" class="toast"></span>
    </div>
    <h1>Context OS Admin</h1>
    <p id="meta" class="meta"></p>
    <h2>Sources</h2>
    <table>
      <thead><tr><th>Source</th><th>Status</th><th>Indexed</th><th>Scopes</th><th>Interval</th><th>Sync</th></tr></thead>
      <tbody id="sources-body"></tbody>
    </table>
    <h2>Eval harness</h2>
    <p id="eval-meta" class="meta"></p>
    <table>
      <thead><tr><th>Metric</th><th>Value</th><th>Target</th></tr></thead>
      <tbody id="eval-body"></tbody>
    </table>
    <h3>Cases</h3>
    <table>
      <thead><tr><th>Case</th><th>Status</th><th>Latency</th><th>precision@must_know</th></tr></thead>
      <tbody id="eval-cases-body"></tbody>
    </table>
    <h2>Connector OAuth</h2>
    <p class="meta">Connect GitHub and Jira without pasting API keys. Requires DATABASE_URL + OAuth app credentials.</p>
    <div class="toolbar">
      <a class="sync-btn" id="oauth-github" href="/v1/oauth/github/start">Connect GitHub</a>
      <a class="sync-btn" id="oauth-jira" href="/v1/oauth/jira/start">Connect Jira</a>
      <span id="oauth-status" class="meta"></span>
    </div>
    <h2>Team invites <span class="meta">(recommended)</span></h2>
    <p class="meta">One-time link — user opens dashboard and gets a personal token automatically. No manual <code>ctx_…</code> handoff.</p>
    <div class="toolbar">
      <input id="invite-name" type="text" placeholder="Имя (principal)" style="padding:0.4rem;"/>
      <label><input type="checkbox" class="invite-scope" value="generate" checked/> generate</label>
      <label><input type="checkbox" class="invite-scope" value="receipt" checked/> receipt</label>
      <label><input type="checkbox" class="invite-scope" value="admin:read"/> admin:read</label>
      <button type="button" id="invite-create-btn">Создать invite</button>
      <span id="invite-toast" class="toast"></span>
    </div>
    <p id="invite-link" class="meta hidden"></p>
    <table>
      <thead><tr><th>Name</th><th>Status</th><th>Expires</th><th>Scopes</th><th></th></tr></thead>
      <tbody id="invites-body"></tbody>
    </table>
    <h2>Team tokens <span class="meta">(manual fallback)</span></h2>
    <p class="meta">Direct token creation when invite links are not suitable. Users normally join via invite or <a href="/dashboard/access">API Access</a>.</p>
    <div class="toolbar">
      <input id="token-name" type="text" placeholder="Имя (principal)" style="padding:0.4rem;"/>
      <label><input type="checkbox" class="token-scope" value="generate" checked/> generate</label>
      <label><input type="checkbox" class="token-scope" value="receipt"/> receipt</label>
      <label><input type="checkbox" class="token-scope" value="admin:read"/> admin:read</label>
      <button type="button" id="token-create-btn">Создать токен</button>
      <span id="token-toast" class="toast"></span>
    </div>
    <p id="token-secret" class="meta hidden"></p>
    <table>
      <thead><tr><th>Name</th><th>Scopes</th><th>Created</th><th>Last used</th><th></th></tr></thead>
      <tbody id="tokens-body"></tbody>
    </table>
    <h2>Token access log</h2>
    <table>
      <thead><tr><th>Time</th><th>Principal</th><th>Method</th><th>Path</th><th>Status</th></tr></thead>
      <tbody id="access-log-body"></tbody>
    </table>
    <h2>Usage receipts</h2>
    <p id="receipts-meta" class="meta"></p>
    <table>
      <thead><tr><th>Time</th><th>Package</th><th>Outcome</th><th>Cited</th><th>Ignored</th></tr></thead>
      <tbody id="receipts-body"></tbody>
    </table>
    <h2>Access audit</h2>
    <div class="toolbar">
      <button type="button" id="audit-prev">← Prev</button>
      <span id="audit-page" class="meta"></span>
      <button type="button" id="audit-next">Next →</button>
    </div>
    <table>
      <thead><tr><th>Time</th><th>Principal</th><th>Source</th><th>Verdict</th></tr></thead>
      <tbody id="audit-body"></tbody>
    </table>
    <p class="meta">API: <code>GET /v1/admin/sources</code> · <code>GET /v1/admin/tokens</code> · <code>POST /v1/admin/tokens</code> · <code>GET /v1/admin/access-log</code> · <code>GET /v1/admin/eval</code> · <code>GET /v1/admin/receipts</code> · <code>GET /v1/admin/audit</code> · <code>POST /v1/admin/sync/{source}</code> · <code>POST /v1/receipt</code></p>
  </div>

  <script>
    const KEY_STORAGE = "ucp_admin_api_key";
    const AUDIT_LIMIT = 20;
    let auditOffset = 0;
    let auditTotal = 0;

    function authHeaders() {
      const key = sessionStorage.getItem(KEY_STORAGE);
      return { "Authorization": "Bearer " + key };
    }

    function apiV1() {
      const m = window.location.pathname.match(/^\\/v1\\/([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)\\/admin/);
      return m ? "/v1/" + m[1] + "/v1" : "/v1";
    }

    function configureTenantLinks() {
      const oauthBase = apiV1() + "/oauth";
      const gh = document.getElementById("oauth-github");
      const jira = document.getElementById("oauth-jira");
      if (gh) gh.href = oauthBase + "/github/start";
      if (jira) jira.href = oauthBase + "/jira/start";
    }

    function esc(s) {
      return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;");
    }

    function showLogin(err) {
      document.getElementById("login-view").classList.remove("hidden");
      document.getElementById("dashboard-view").classList.add("hidden");
      const el = document.getElementById("login-error");
      if (err) { el.textContent = err; el.classList.remove("hidden"); }
      else { el.classList.add("hidden"); }
    }

    function showDashboard() {
      document.getElementById("login-view").classList.add("hidden");
      document.getElementById("dashboard-view").classList.remove("hidden");
    }

    async function loadEval() {
      const resp = await fetch(apiV1() + "/admin/eval", { headers: authHeaders() });
      if (!resp.ok) return;
      const data = await resp.json();
      const meta = document.getElementById("eval-meta");
      const body = document.getElementById("eval-body");
      const casesBody = document.getElementById("eval-cases-body");
      if (data.status !== "ok") {
        meta.textContent = data.message || "Eval report missing";
        body.innerHTML = "<tr><td colspan='3'>" + esc(data.message) + "</td></tr>";
        casesBody.innerHTML = "";
        return;
      }
      const agg = data.aggregate || {};
      const targets = agg.targets || {};
      meta.textContent =
        "run " + esc(data.run_at) + " · " + (agg.cases_passed || 0) + "/" + (agg.cases_ok || 0) + " passed · llm=" + (data.llm ? "on" : "off");
      const rows = [
        ["must_know_precision (mean)", agg.must_know_precision_mean, targets.must_know_precision],
        ["must_know_gold_recall (mean)", agg.must_know_gold_recall_mean, "—"],
        ["decision_recall (mean)", agg.decision_recall_mean, targets.decision_recall],
        ["latency p50 (ms)", (agg.latency_ms || {}).p50, "—"],
        ["latency p95 (ms)", (agg.latency_ms || {}).p95, targets.latency_p95_ms],
      ];
      body.innerHTML = rows.map(r =>
        "<tr><td>" + esc(r[0]) + "</td><td>" + esc(r[1]) + "</td><td>" + esc(r[2]) + "</td></tr>"
      ).join("");
      casesBody.innerHTML = (data.cases || []).map(c => {
        const sc = c.scores || {};
        const st = c.status === "ok" ? (c.passed ? "PASS" : "FAIL") : esc(c.status);
        return "<tr><td>" + esc(c.id) + "</td><td>" + st + "</td><td>" +
          esc(c.latency_ms != null ? c.latency_ms + " ms" : "—") + "</td><td>" +
          esc(sc.must_know_precision != null ? sc.must_know_precision : "—") + "</td></tr>";
      }).join("") || "<tr><td colspan='4'>No cases</td></tr>";
    }

    async function loadInvites() {
      const resp = await fetch(apiV1() + "/admin/invites", { headers: authHeaders() });
      if (!resp.ok) return;
      const data = await resp.json();
      const body = document.getElementById("invites-body");
      body.innerHTML = (data.invites || []).map(i =>
        "<tr><td>" + esc(i.principal_name) + "</td><td>" + esc(i.status) + "</td>" +
        "<td>" + esc(i.expires_at) + "</td><td>" + esc((i.scopes || []).join(", ")) + "</td>" +
        "<td>" + (i.status === "pending"
          ? "<button type='button' class='sync-btn' data-invite-id='" + esc(i.id) + "'>Revoke</button>"
          : "—") + "</td></tr>"
      ).join("") || "<tr><td colspan='5'>No invites yet</td></tr>";
      body.querySelectorAll("[data-invite-id]").forEach(btn => {
        btn.addEventListener("click", () => revokeInvite(btn.dataset.inviteId));
      });
    }

    async function revokeInvite(id) {
      const toast = document.getElementById("invite-toast");
      const resp = await fetch(apiV1() + "/admin/invites/" + encodeURIComponent(id), {
        method: "DELETE",
        headers: authHeaders()
      });
      toast.textContent = resp.ok ? "Invite revoked" : "Revoke failed: " + resp.status;
      await loadInvites();
    }

    async function loadTokens() {
      const resp = await fetch(apiV1() + "/admin/tokens", { headers: authHeaders() });
      if (!resp.ok) return;
      const data = await resp.json();
      const body = document.getElementById("tokens-body");
      body.innerHTML = (data.tokens || []).map(t =>
        "<tr><td>" + esc(t.name) + "</td><td>" + esc((t.scopes || []).join(", ")) + "</td>" +
        "<td>" + esc(t.created_at) + "</td><td>" + esc(t.last_used_at || "—") + "</td>" +
        "<td><button type='button' class='sync-btn' data-token-id='" + esc(t.id) + "'>Revoke</button></td></tr>"
      ).join("") || "<tr><td colspan='5'>No personal tokens yet</td></tr>";
      body.querySelectorAll("[data-token-id]").forEach(btn => {
        btn.addEventListener("click", () => revokeToken(btn.dataset.tokenId));
      });
    }

    async function loadAccessLog() {
      const resp = await fetch(apiV1() + "/admin/access-log?limit=15", { headers: authHeaders() });
      if (!resp.ok) return;
      const data = await resp.json();
      const body = document.getElementById("access-log-body");
      body.innerHTML = (data.entries || []).map(e =>
        "<tr><td>" + esc(e.created_at) + "</td><td>" + esc(e.principal) + "</td>" +
        "<td>" + esc(e.method) + "</td><td>" + esc(e.path) + "</td><td>" + esc(e.status) + "</td></tr>"
      ).join("") || "<tr><td colspan='5'>No token access yet</td></tr>";
    }

    async function loadOAuth() {
      const el = document.getElementById("oauth-status");
      if (!el) return;
      const resp = await fetch(apiV1() + "/oauth/status");
      if (!resp.ok) { el.textContent = "OAuth status unavailable"; return; }
      const data = await resp.json();
      const parts = Object.entries(data.providers || {}).map(
        ([k, v]) => k + ": " + (v.connected ? "connected (" + (v.source || "oauth") + ")" : "off")
      );
      el.textContent = parts.length ? parts.join(" · ") : "No connectors connected";
    }

    async function revokeToken(id) {
      const toast = document.getElementById("token-toast");
      const resp = await fetch(apiV1() + "/admin/tokens/" + encodeURIComponent(id), {
        method: "DELETE",
        headers: authHeaders()
      });
      toast.textContent = resp.ok ? "Token revoked" : "Revoke failed: " + resp.status;
      await loadTokens();
      await loadOAuth();
    }

    async function loadReceipts() {
      const resp = await fetch(apiV1() + "/admin/receipts?limit=15", { headers: authHeaders() });
      if (!resp.ok) return;
      const data = await resp.json();
      const agg = data.aggregate || {};
      document.getElementById("receipts-meta").textContent =
        "total " + (agg.total || 0) + " · cited " + (agg.claims_cited_total || 0) +
        " · ignored " + (agg.claims_ignored_total || 0);
      const body = document.getElementById("receipts-body");
      body.innerHTML = (data.receipts || []).map(row => {
        const r = row.receipt || {};
        return "<tr><td>" + esc(row.stored_at) + "</td><td>" + esc(r.package_id) + "</td>" +
          "<td>" + esc(r.outcome) + "</td><td>" + (r.claims_cited || []).length + "</td>" +
          "<td>" + (r.claims_ignored || []).length + "</td></tr>";
      }).join("") || "<tr><td colspan='5'>No receipts yet — use Sidebar pin/dismiss</td></tr>";
    }

    async function loadAudit() {
      const resp = await fetch(apiV1() + "/admin/audit?limit=" + AUDIT_LIMIT + "&offset=" + auditOffset, {
        headers: authHeaders()
      });
      if (!resp.ok) return;
      const data = await resp.json();
      auditTotal = data.total || 0;
      document.getElementById("audit-page").textContent =
        "Стр. " + (Math.floor(auditOffset / AUDIT_LIMIT) + 1) +
        " · " + auditOffset + "–" + Math.min(auditOffset + AUDIT_LIMIT, auditTotal) + " из " + auditTotal;
      const auditBody = document.getElementById("audit-body");
      auditBody.innerHTML = (data.entries || []).map(e =>
        "<tr><td>" + esc(e.created_at) + "</td><td>" + esc(e.principal) + "</td>" +
        "<td>" + esc(e.source_system) + "</td><td>" + esc(e.verdict) + "</td></tr>"
      ).join("") || "<tr><td colspan='4'>No audit entries yet</td></tr>";
      document.getElementById("audit-prev").disabled = auditOffset <= 0;
      document.getElementById("audit-next").disabled = auditOffset + AUDIT_LIMIT >= auditTotal;
    }

    async function syncSource(source) {
      const toast = document.getElementById("sync-toast");
      toast.textContent = "Sync " + source + "…";
      const resp = await fetch(apiV1() + "/admin/sync/" + encodeURIComponent(source), {
        method: "POST",
        headers: authHeaders()
      });
      if (!resp.ok) {
        toast.textContent = "Sync failed: " + resp.status;
        return;
      }
      const data = await resp.json();
      toast.textContent = source + " queued · task " + data.task_id;
      setTimeout(loadDashboard, 3000);
    }

    async function loadDashboard() {
      const key = sessionStorage.getItem(KEY_STORAGE);
      if (!key) { showLogin(); return; }
      const resp = await fetch(apiV1() + "/admin/sources", { headers: authHeaders() });
      if (resp.status === 401) {
        sessionStorage.removeItem(KEY_STORAGE);
        showLogin("Неверный API key");
        return;
      }
      if (!resp.ok) {
        showLogin("Ошибка " + resp.status + ": " + (await resp.text()).slice(0, 200));
        return;
      }
      const data = await resp.json();
      showDashboard();
      document.getElementById("meta").textContent =
        "engine " + data.engine_version + " · generated " + data.generated_at +
        " · SpiceDB " + (data.spicedb_enabled ? "on" : "off");

      const srcBody = document.getElementById("sources-body");
      srcBody.innerHTML = (data.sources || []).map(s => {
        const scopes = (s.configured_scopes || []).join(", ") || "—";
        const st = esc(s.status);
        return "<tr><td><strong>" + esc(s.source) + "</strong></td>" +
          "<td><span class='" + st + "'>" + st + "</span></td>" +
          "<td>" + (s.indexed_entities || 0) + "</td>" +
          "<td>" + esc(scopes) + "</td>" +
          "<td>" + (s.sync_interval_seconds || "—") + "s</td>" +
          "<td><button type='button' class='sync-btn' data-source='" + esc(s.source) + "'>Sync</button></td></tr>";
      }).join("") || "<tr><td colspan='6'>No sources</td></tr>";
      srcBody.querySelectorAll(".sync-btn").forEach(btn => {
        btn.addEventListener("click", () => syncSource(btn.dataset.source));
      });

      await loadEval();
      await loadInvites();
      await loadTokens();
      await loadOAuth();
      await loadAccessLog();
      await loadReceipts();
      await loadAudit();
    }

    document.getElementById("token-create-btn").addEventListener("click", async () => {
      const name = document.getElementById("token-name").value.trim();
      const scopes = [...document.querySelectorAll(".token-scope:checked")].map(el => el.value);
      const toast = document.getElementById("token-toast");
      const secretEl = document.getElementById("token-secret");
      if (!name || !scopes.length) {
        toast.textContent = "Укажите имя и хотя бы один scope";
        return;
      }
      const resp = await fetch(apiV1() + "/admin/tokens", {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ name, scopes })
      });
      if (!resp.ok) {
        toast.textContent = "Create failed: " + resp.status;
        return;
      }
      const data = await resp.json();
      toast.textContent = "Токен создан";
      secretEl.textContent = "Secret (скопируйте сейчас): " + data.secret;
      secretEl.classList.remove("hidden");
      document.getElementById("token-name").value = "";
      await loadTokens();
      await loadOAuth();
    });

    document.getElementById("invite-create-btn").addEventListener("click", async () => {
      const name = document.getElementById("invite-name").value.trim();
      const scopes = [...document.querySelectorAll(".invite-scope:checked")].map(el => el.value);
      const toast = document.getElementById("invite-toast");
      const linkEl = document.getElementById("invite-link");
      if (!name || !scopes.length) {
        toast.textContent = "Укажите имя и хотя бы один scope";
        return;
      }
      const resp = await fetch(apiV1() + "/admin/invites", {
        method: "POST",
        headers: { ...authHeaders(), "Content-Type": "application/json" },
        body: JSON.stringify({ name, scopes })
      });
      if (!resp.ok) {
        toast.textContent = "Invite failed: " + resp.status;
        return;
      }
      const data = await resp.json();
      toast.textContent = "Invite создан — отправьте ссылку пользователю";
      const url = data.invite_url || data.invite_path || "";
      linkEl.innerHTML = "Invite link: <a href='" + esc(url) + "'>" + esc(url) + "</a>";
      linkEl.classList.remove("hidden");
      document.getElementById("invite-name").value = "";
      await loadInvites();
    });

    document.getElementById("login-btn").addEventListener("click", () => {
      const key = document.getElementById("api-key").value.trim();
      if (!key) { showLogin("Введите API key"); return; }
      sessionStorage.setItem(KEY_STORAGE, key);
      loadDashboard();
    });
    document.getElementById("api-key").addEventListener("keydown", e => {
      if (e.key === "Enter") document.getElementById("login-btn").click();
    });
    document.getElementById("refresh-btn").addEventListener("click", loadDashboard);
    document.getElementById("audit-prev").addEventListener("click", () => {
      auditOffset = Math.max(0, auditOffset - AUDIT_LIMIT);
      loadAudit();
    });
    document.getElementById("audit-next").addEventListener("click", () => {
      if (auditOffset + AUDIT_LIMIT < auditTotal) {
        auditOffset += AUDIT_LIMIT;
        loadAudit();
      }
    });
    document.getElementById("logout-btn").addEventListener("click", () => {
      sessionStorage.removeItem(KEY_STORAGE);
      document.getElementById("api-key").value = "";
      showLogin();
    });

    configureTenantLinks();
    loadDashboard();
  </script>
</body>
</html>"""
