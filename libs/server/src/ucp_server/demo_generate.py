"""Public browser demo: generate UCP from a GitHub issue ref (no auth)."""
from __future__ import annotations

import re
from typing import Any, Optional

from ucp_gen.build import build_package
from ucp_gen.github import GitHubError, fetch_issue_bundle

import ucp

from .token_savings import _estimate_raw_tokens_github

_REF = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")


def parse_github_ref(ref: str) -> tuple[str, str, int]:
    match = _REF.match((ref or "").strip())
    if not match:
        raise ValueError("expected owner/repo#number, e.g. microsoft/vscode#519")
    return match["owner"], match["repo"], int(match["number"])


def generate_demo_package(
    ref: str,
    *,
    github_token: Optional[str] = None,
) -> dict[str, Any]:
    owner, repo, number = parse_github_ref(ref)
    try:
        bundle = fetch_issue_bundle(owner, repo, number, token=github_token)
    except GitHubError as exc:
        raise ValueError(str(exc)) from exc
    package = build_package(bundle)
    ucp.validate(package)
    raw_tokens = _estimate_raw_tokens_github(bundle)
    ucp_tokens = ucp.estimate_tokens(ucp.Package.model_validate(package).render())
    return {
        "package": package,
        "stats": {
            "ref": f"{owner}/{repo}#{number}",
            "comments_fetched": len(bundle.get("comments") or []),
            "comments_total": int((bundle.get("issue") or {}).get("comments") or 0),
            "raw_tokens": raw_tokens,
            "ucp_tokens": ucp_tokens,
            "reduction_pct": max(0, int(100 - (ucp_tokens * 100 / max(raw_tokens, 1)))),
        },
    }
