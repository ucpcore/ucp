"""Fetch selectable index scope resources from upstream APIs."""
from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from .config import Settings
from .connector_config import CONNECTOR_SPECS
from .oauth import get_connector_token
from .platform_db import ConnectorCredentialRow, get_session_factory, postgres_available

_RESOURCE_FIELDS: dict[tuple[str, str], str] = {
    ("github", "repos"): "github_repos",
    ("jira", "projects"): "jira_projects",
    ("jira", "spaces"): "confluence_spaces",
}


def _load_metadata(settings: Settings, provider: str) -> dict[str, Any]:
    if not postgres_available(settings.database_url):
        return {}
    Session = get_session_factory(settings.database_url)
    with Session() as session:
        row = (
            session.query(ConnectorCredentialRow)
            .filter_by(provider=provider)
            .one_or_none()
        )
        if row is None or not row.metadata_json:
            return {}
        try:
            data = json.loads(row.metadata_json)
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}


def _item(value: str, label: str) -> dict[str, str]:
    return {"value": value, "label": label}


async def _github_repos(token: str) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    page = 1
    async with httpx.AsyncClient(timeout=30.0) as client:
        while page <= 5:
            resp = await client.get(
                "https://api.github.com/user/repos",
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                params={
                    "per_page": 100,
                    "page": page,
                    "sort": "updated",
                    "affiliation": "owner,collaborator,organization_member",
                },
            )
            if resp.status_code in (401, 403):
                raise RuntimeError("GitHub token rejected — check scopes (repo)")
            resp.raise_for_status()
            batch = resp.json()
            if not isinstance(batch, list) or not batch:
                break
            for repo in batch:
                full_name = str(repo.get("full_name") or "").strip()
                if not full_name:
                    continue
                private = " 🔒" if repo.get("private") else ""
                items.append(_item(full_name, f"{full_name}{private}"))
            if len(batch) < 100:
                break
            page += 1
    return items


def _atlassian_auth(
    settings: Settings, meta: dict[str, Any]
) -> tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """Return (base_url, cloud_id, token, email_for_basic_auth)."""
    token = get_connector_token(settings, "jira")
    if not token:
        return None, None, None, None
    base_url = (
        str(meta.get("jira_base_url") or "").rstrip("/")
        or (settings.jira_base_url or "").rstrip("/")
        or None
    )
    cloud_id = str(meta.get("cloud_id") or "").strip() or None
    email = (
        settings.jira_email
        if settings.jira_api_token and token == settings.jira_api_token and settings.jira_email
        else None
    )
    return base_url, cloud_id, token, email


async def _jira_projects(
    settings: Settings,
    *,
    base_url: Optional[str],
    cloud_id: Optional[str],
    token: str,
    email: Optional[str],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        if cloud_id:
            url = f"https://api.atlassian.com/ex/jira/{cloud_id}/rest/api/3/project/search"
            headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
            params: dict[str, Any] = {"maxResults": 50, "startAt": 0}
            while True:
                resp = await client.get(url, headers=headers, params=params)
                if resp.status_code in (401, 403):
                    raise RuntimeError("Atlassian token rejected — reconnect Jira OAuth")
                resp.raise_for_status()
                data = resp.json()
                for project in data.get("values") or []:
                    key = str(project.get("key") or "").strip().upper()
                    name = str(project.get("name") or key).strip()
                    if key:
                        items.append(_item(key, f"{name} ({key})"))
                if data.get("isLast", True):
                    break
                params["startAt"] = int(data.get("startAt", 0)) + int(data.get("maxResults", 50))
        elif base_url:
            headers = {"Accept": "application/json"}
            auth = (email, token) if email else None
            if not email:
                headers["Authorization"] = f"Bearer {token}"
            start = 0
            while start < 500:
                resp = await client.get(
                    f"{base_url}/rest/api/3/project/search",
                    headers=headers,
                    auth=auth,
                    params={"maxResults": 50, "startAt": start},
                )
                if resp.status_code in (401, 403):
                    raise RuntimeError("Jira credentials rejected — check JIRA_EMAIL and JIRA_API_TOKEN")
                resp.raise_for_status()
                data = resp.json()
                for project in data.get("values") or []:
                    key = str(project.get("key") or "").strip().upper()
                    name = str(project.get("name") or key).strip()
                    if key:
                        items.append(_item(key, f"{name} ({key})"))
                if data.get("isLast", True):
                    break
                start += int(data.get("maxResults", 50))
        else:
            raise RuntimeError("Jira site URL unknown — set JIRA_BASE_URL or reconnect OAuth")
    return items


async def _confluence_spaces(
    settings: Settings,
    *,
    base_url: Optional[str],
    cloud_id: Optional[str],
    token: str,
    email: Optional[str],
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        if cloud_id:
            url = f"https://api.atlassian.com/ex/confluence/{cloud_id}/wiki/rest/api/space"
            headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
            start = 0
            while start < 500:
                resp = await client.get(url, headers=headers, params={"limit": 100, "start": start})
                if resp.status_code in (401, 403):
                    raise RuntimeError(
                        "Confluence access denied — OAuth may need read:confluence-space.summary scope"
                    )
                resp.raise_for_status()
                data = resp.json()
                for space in data.get("results") or []:
                    key = str(space.get("key") or "").strip().upper()
                    name = str(space.get("name") or key).strip()
                    if key:
                        items.append(_item(key, f"{name} ({key})"))
                size = int(data.get("size", 0))
                if size < 100:
                    break
                start += size
        elif base_url:
            start = 0
            while start < 500:
                kwargs: dict[str, Any] = {
                    "params": {"limit": 100, "start": start},
                    "headers": {"Accept": "application/json"},
                }
                if email:
                    kwargs["auth"] = (email, token)
                else:
                    kwargs["headers"]["Authorization"] = f"Bearer {token}"
                resp = await client.get(f"{base_url}/wiki/rest/api/space", **kwargs)
                if resp.status_code in (401, 403):
                    raise RuntimeError("Confluence credentials rejected")
                resp.raise_for_status()
                data = resp.json()
                for space in data.get("results") or []:
                    key = str(space.get("key") or "").strip().upper()
                    name = str(space.get("name") or key).strip()
                    if key:
                        items.append(_item(key, f"{name} ({key})"))
                size = int(data.get("size", 0))
                if size < 100:
                    break
                start += size
        else:
            raise RuntimeError("Confluence site URL unknown — set JIRA_BASE_URL or reconnect OAuth")
    return items


async def list_connector_resources(
    settings: Settings,
    provider: str,
    field: str,
) -> dict[str, Any]:
    if provider not in CONNECTOR_SPECS:
        raise ValueError(f"unknown connector: {provider}")
    if (provider, field) not in _RESOURCE_FIELDS:
        raise ValueError(f"no resource picker for {provider}.{field}")

    if field == "repos":
        token = get_connector_token(settings, "github")
        if not token:
            raise RuntimeError("GitHub not connected — set GITHUB_TOKEN or use OAuth")
        items = await _github_repos(token)
    elif field == "projects":
        meta = _load_metadata(settings, "jira")
        base_url, cloud_id, token, email = _atlassian_auth(settings, meta)
        if not token:
            raise RuntimeError("Jira not connected — set JIRA_API_TOKEN or use OAuth")
        items = await _jira_projects(
            settings,
            base_url=base_url,
            cloud_id=cloud_id,
            token=token,
            email=email,
        )
    elif field == "spaces":
        meta = _load_metadata(settings, "jira")
        base_url, cloud_id, token, email = _atlassian_auth(settings, meta)
        if not token:
            raise RuntimeError("Atlassian not connected — required for Confluence spaces")
        items = await _confluence_spaces(
            settings,
            base_url=base_url,
            cloud_id=cloud_id,
            token=token,
            email=email,
        )
    else:
        raise ValueError(f"unsupported field: {field}")

    return {"provider": provider, "field": field, "items": items}
