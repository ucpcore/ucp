"""Jira REST client (API v2): fetches an issue bundle for UCP generation.

Works with Jira Cloud (email + API token, Basic auth) and Jira Server/DC
(personal access token, Bearer auth). Network access is confined to this
module; ``build_jira.py`` is pure and works on the returned bundle.

Environment:
    JIRA_BASE_URL   e.g. https://yourcompany.atlassian.net
    JIRA_EMAIL      Jira Cloud account email (Basic auth)
    JIRA_API_TOKEN  API token (Cloud) or PAT (Server/DC)
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx


class JiraError(RuntimeError):
    pass


def _client(
    base_url: Optional[str], email: Optional[str], token: Optional[str]
) -> httpx.Client:
    base_url = base_url or os.environ.get("JIRA_BASE_URL")
    if not base_url:
        raise JiraError("Jira base URL is required (--base-url or JIRA_BASE_URL)")
    email = email or os.environ.get("JIRA_EMAIL")
    token = token or os.environ.get("JIRA_API_TOKEN")
    if not token:
        raise JiraError("Jira token is required (--token or JIRA_API_TOKEN)")

    kwargs: dict[str, Any] = {
        "base_url": base_url.rstrip("/"),
        "headers": {"Accept": "application/json", "User-Agent": "ucp-gen"},
        "timeout": 30.0,
        "follow_redirects": True,
    }
    if email:  # Jira Cloud
        kwargs["auth"] = (email, token)
    else:  # Server / Data Center personal access token
        kwargs["headers"]["Authorization"] = f"Bearer {token}"
    return httpx.Client(**kwargs)


def _get_json(client: httpx.Client, url: str, **params: Any) -> Any:
    resp = client.get(url, params=params or None)
    if resp.status_code == 404:
        raise JiraError(f"not found: {url}")
    if resp.status_code in (401, 403):
        raise JiraError(f"Jira auth failed ({resp.status_code}); check JIRA_EMAIL/JIRA_API_TOKEN")
    resp.raise_for_status()
    return resp.json()


def fetch_issue_bundle(
    key: str,
    base_url: Optional[str] = None,
    email: Optional[str] = None,
    token: Optional[str] = None,
) -> dict[str, Any]:
    """Fetch a Jira issue with full comments and changelog.

    Returns a JSON-serializable bundle: ``{"base_url", "issue", "comments"}``
    (the changelog rides inside ``issue["changelog"]["histories"]``).
    """
    with _client(base_url, email, token) as client:
        issue = _get_json(client, f"/rest/api/2/issue/{key}", expand="changelog")

        comments: list[dict] = []
        start = 0
        while True:
            page = _get_json(
                client, f"/rest/api/2/issue/{key}/comment", startAt=start, maxResults=100
            )
            comments.extend(page.get("comments", []))
            start += len(page.get("comments", []))
            if start >= page.get("total", 0) or not page.get("comments"):
                break

    return {"base_url": str(client.base_url), "issue": issue, "comments": comments}
