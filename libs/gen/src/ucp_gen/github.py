"""GitHub REST client: fetches everything needed to build a UCP for an issue.

Network access is confined to this module; ``build.py`` is pure and works
on the plain-dict bundle returned by :func:`fetch_issue_bundle`.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx

API = "https://api.github.com"


class GitHubError(RuntimeError):
    pass


def _client(token: Optional[str] = None) -> httpx.Client:
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ucp-gen",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=API, headers=headers, timeout=30.0, follow_redirects=True)


def _get_json(client: httpx.Client, url: str, **params: Any) -> Any:
    resp = client.get(url, params=params or None)
    if resp.status_code == 404:
        raise GitHubError(f"not found: {url}")
    if resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
        raise GitHubError("GitHub rate limit exceeded; set GITHUB_TOKEN to raise the limit")
    resp.raise_for_status()
    return resp.json()


def _paginate(client: httpx.Client, url: str, limit: int = 200) -> list[dict]:
    items: list[dict] = []
    page = 1
    while len(items) < limit:
        batch = _get_json(client, url, per_page=100, page=page)
        if not batch:
            break
        items.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return items[:limit]


def fetch_issue_bundle(
    owner: str, repo: str, number: int, token: Optional[str] = None
) -> dict[str, Any]:
    """Fetch an issue with comments, timeline, and linked pull requests.

    Returns a JSON-serializable bundle:
    ``{"owner", "repo", "issue", "comments", "timeline", "linked_pulls"}``.
    """
    with _client(token) as client:
        base = f"/repos/{owner}/{repo}/issues/{number}"
        issue = _get_json(client, base)
        comments = _paginate(client, f"{base}/comments")
        timeline = _paginate(client, f"{base}/timeline")

        # Cross-referenced PRs show up in the timeline; fetch their real state
        # (merged / open / closed) because the timeline entry alone lacks it.
        pull_numbers: list[int] = []
        for event in timeline:
            source_issue = (event.get("source") or {}).get("issue") or {}
            if event.get("event") == "cross-referenced" and source_issue.get("pull_request"):
                same_repo = (source_issue.get("repository") or {}).get("full_name")
                if same_repo == f"{owner}/{repo}":
                    pull_numbers.append(source_issue["number"])

        linked_pulls = []
        for pull_number in dict.fromkeys(pull_numbers):
            try:
                linked_pulls.append(
                    _get_json(client, f"/repos/{owner}/{repo}/pulls/{pull_number}")
                )
            except GitHubError:
                continue

    return {
        "owner": owner,
        "repo": repo,
        "issue": issue,
        "comments": comments,
        "timeline": timeline,
        "linked_pulls": linked_pulls,
    }
