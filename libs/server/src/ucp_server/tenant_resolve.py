"""Resolve tenant slug/id from portal session or request context."""
from __future__ import annotations

from typing import Any, Optional

from starlette.requests import Request

from .config import Settings
from .portal_auth import get_portal_session
from .tenant_store import get_tenant_store
from .user_store import get_user_store


def tenant_slug_from_user_tenant_id(settings: Settings, tenant_id: Optional[str]) -> Optional[str]:
    if not tenant_id:
        return None
    tenant = get_tenant_store(settings).get_by_id(tenant_id)
    return tenant.slug if tenant else None


def resolve_tenant_slug(
    settings: Settings,
    request: Optional[Request] = None,
    *,
    explicit_slug: Optional[str] = None,
) -> Optional[str]:
    if explicit_slug and explicit_slug.strip():
        return explicit_slug.strip().lower()
    if request is not None:
        state_slug = getattr(request.state, "tenant_slug", None)
        if state_slug:
            return str(state_slug)
        session = get_portal_session(request, settings)
        if session is not None:
            user = get_user_store(settings).get_by_id(session.user_id)
            if user is not None:
                slug = tenant_slug_from_user_tenant_id(settings, user.tenant_id)
                if slug:
                    return slug
    return settings.tenant_slug


def resolve_tenant_id(settings: Settings, request: Optional[Request] = None) -> Optional[str]:
    if request is not None:
        state_id = getattr(request.state, "tenant_id", None)
        if state_id:
            return str(state_id)
        session = get_portal_session(request, settings)
        if session is not None:
            user = get_user_store(settings).get_by_id(session.user_id)
            if user and user.tenant_id:
                return user.tenant_id
    slug = resolve_tenant_slug(settings, request)
    if slug:
        tenant = get_tenant_store(settings).get_by_slug(slug)
        return tenant.id if tenant else None
    return None


def build_setup_for_request(settings: Settings, request: Optional[Request] = None) -> dict[str, Any]:
    from . import __version__
    from .hosted_view import build_local_setup, build_setup_payload
    from .sidebar_auth import build_sidebar_setup

    sidebar = build_sidebar_setup(settings, tenant_slug=resolve_tenant_slug(settings, request))
    slug = resolve_tenant_slug(settings, request)
    public = settings.public_base_url or settings.effective_api_base_url()
    if slug and public:
        return build_setup_payload(
            tenant_slug=slug,
            public_base_url=public,
            version=__version__,
            sidebar=sidebar,
        )
    from .hosted_view import display_host_hint  # noqa: PLC0415 — avoid cycle at import

    host_hint = display_host_hint(settings.host, settings.port)
    return build_local_setup(version=__version__, host_hint=host_hint, sidebar=sidebar)
