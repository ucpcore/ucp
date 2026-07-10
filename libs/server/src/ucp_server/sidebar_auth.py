"""Chrome Sidebar connect flow — portal login + personal token handoff."""
from __future__ import annotations

import html
import re
from typing import Any, Optional
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .brand import LOGO_SVG, PRODUCT_NAME
from .config import Settings
from .portal_auth import get_portal_session
from .tenant import public_api_url
from .token_store import get_token_store
from .user_store import get_user_store

_EXTENSION_ID_RE = re.compile(r"^[a-f]{32}$")
_SIDEBAR_CLIENT_LABEL = "Chrome Sidebar"


def _sidebar_api_url(settings: Settings) -> str:
    if settings.tenant_slug and settings.public_base_url:
        return public_api_url(
            settings.public_base_url,
            settings.tenant_slug,
            "",
        ).rstrip("/")
    host = settings.host.strip() or "127.0.0.1"
    if host in {"0.0.0.0", "::", "[::]"}:
        host = "127.0.0.1"
    return f"http://{host}:{settings.port}"


def _sidebar_api_url_for_user(settings: Settings, tenant_id: Optional[str]) -> str:
    from .tenant_store import get_tenant_store

    if tenant_id:
        tenant = get_tenant_store(settings).get_by_id(tenant_id)
        if tenant and settings.effective_api_base_url():
            return public_api_url(settings.effective_api_base_url(), tenant.slug, "").rstrip("/")
    return _sidebar_api_url(settings)


def build_sidebar_setup(settings: Settings, *, tenant_slug: Optional[str] = None) -> dict[str, Any]:
    slug = tenant_slug or settings.tenant_slug
    api_base = settings.effective_api_base_url()
    portal_base = settings.effective_portal_base_url()
    if slug and api_base:
        api_url = public_api_url(api_base, slug, "").rstrip("/")
        connect_url = f"{api_base}/v1/auth/sidebar/connect"
        mode = "hosted"
    else:
        api_url = _sidebar_api_url(settings)
        connect_url = f"{api_url}/v1/auth/sidebar/connect"
        mode = "self-hosted"
    return {
        "mode": mode,
        "connect_url": connect_url,
        "api_url": api_url,
        "tenant_slug": slug,
        "portal_url": f"{portal_base}/dashboard",
        "setup_json_url": f"{api_base or api_url}/setup?format=json",
    }


def _revoke_sidebar_tokens(settings: Settings, user_id: str, principal: str) -> None:
    store = get_token_store(settings)
    for row in store.list_for_user(user_id, principal):
        if row.get("client_label") == _SIDEBAR_CLIENT_LABEL and row.get("revoked_at") is None:
            store.revoke_for_user(row["id"], user_id, principal)


def _render_login_page(*, extension_id: str, settings: Settings, error: Optional[str] = None) -> HTMLResponse:
    return_to = f"/v1/auth/sidebar/connect?{urlencode({'extension_id': extension_id})}"
    portal_login = f"/dashboard/login?{urlencode({'return': return_to})}"
    err = f'<p class="err">{html.escape(error)}</p>' if error else ""
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{PRODUCT_NAME} — подключение Sidebar</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 28rem; line-height: 1.5; padding: 0 1rem; }}
    .brand {{ display: flex; align-items: center; gap: 0.75rem; margin-bottom: 1rem; }}
    .brand svg {{ width: 2rem; height: 2rem; color: #0f172a; }}
    .meta {{ color: #64748b; font-size: 0.9rem; }}
    a {{ color: #2563eb; }}
    .err {{ color: #b91c1c; }}
  </style>
</head>
<body>
  <div class="brand">{LOGO_SVG}<strong>{PRODUCT_NAME}</strong></div>
  <h1>Подключить Chrome Sidebar</h1>
  <p class="meta">Войдите в Portal — токен выдастся автоматически, без ручного копирования.</p>
  {err}
  <p><a href="{html.escape(portal_login)}">Войти через Portal</a></p>
</body>
</html>"""
    )


def _render_done_page(
    *,
    extension_id: str,
    secret: str,
    email: str,
    api_url: str,
) -> HTMLResponse:
    payload = {
        "type": "contextos:sidebar-connected",
        "secret": secret,
        "email": email,
        "apiUrl": api_url,
    }
    import json

    payload_json = json.dumps(payload, ensure_ascii=False)
    ext = html.escape(extension_id)
    return HTMLResponse(
        f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Sidebar подключён — {PRODUCT_NAME}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem auto; max-width: 28rem; line-height: 1.5; padding: 0 1rem; }}
    .ok {{ color: #15803d; }}
    .err {{ color: #b91c1c; }}
    .meta {{ color: #64748b; font-size: 0.9rem; }}
  </style>
</head>
<body>
  <h1>Chrome Sidebar</h1>
  <p id="status" class="meta">Передаём токен в расширение…</p>
  <p class="meta">После успеха закройте вкладку и откройте Side Panel на задаче.</p>
  <script>
    (async () => {{
      const extId = "{ext}";
      const payload = {payload_json};
      const status = document.getElementById("status");
      try {{
        if (!chrome?.runtime?.sendMessage) {{
          throw new Error("Откройте эту страницу из кнопки «Подключить через Portal» в настройках расширения.");
        }}
        const resp = await chrome.runtime.sendMessage(extId, payload);
        if (!resp?.ok) throw new Error(resp?.error || "расширение не ответило");
        status.textContent = "Готово! Sidebar подключён — можно закрыть вкладку.";
        status.className = "ok";
      }} catch (err) {{
        status.textContent = "Ошибка: " + (err?.message || String(err));
        status.className = "err";
      }}
    }})();
  </script>
</body>
</html>"""
    )


def build_sidebar_auth_router(settings: Settings) -> APIRouter:
    router = APIRouter(prefix="/v1/auth/sidebar", tags=["auth"])

    @router.get("/connect")
    async def sidebar_connect(
        request: Request,
        extension_id: str = Query(min_length=32, max_length=32),
    ) -> HTMLResponse:
        if not _EXTENSION_ID_RE.fullmatch(extension_id.lower()):
            raise StarletteHTTPException(400, "invalid extension_id")

        session = get_portal_session(request, settings)
        if session is None:
            return _render_login_page(extension_id=extension_id, settings=settings)

        user = get_user_store(settings).get_by_id(session.user_id)
        if user is None:
            return _render_login_page(
                extension_id=extension_id,
                settings=settings,
                error="Сессия истекла — войдите снова.",
            )

        if not settings.allow_self_service_tokens and user.role != "admin":
            raise StarletteHTTPException(
                403,
                "token self-service disabled — ask admin for API Access token",
            )

        store = get_token_store(settings)
        _revoke_sidebar_tokens(settings, user.id, user.display_name)
        try:
            _token, raw = store.create(
                name=user.display_name,
                scopes=["generate", "receipt"],
                user_id=user.id,
                client_label=_SIDEBAR_CLIENT_LABEL,
                auth_method="oauth",
            )
        except ValueError as exc:
            raise StarletteHTTPException(400, str(exc)) from exc

        return _render_done_page(
            extension_id=extension_id,
            secret=raw,
            email=user.email,
            api_url=_sidebar_api_url_for_user(settings, user.tenant_id),
        )

    return router
