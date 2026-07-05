#!/usr/bin/env python3
"""Context benchmark: raw GitHub issue thread vs its UCP rendering.

Reproduces the numbers published in the README. For each issue we compare,
using the same token estimator (~4 chars/token) on both sides:

  raw   — title + issue body + comment bodies + linked-PR bodies, i.e. the
          text you would otherwise paste into an LLM (first 200 comments);
  ucp   — the canonical CommonMark rendering of the generated package;
  1500  — the same rendering under a 1500-token budget (salience truncation).

Usage:
    pip install ucp-gen            # >= 0.1.1
    export GITHUB_TOKEN=...        # recommended, raises the API rate limit
    python tools/benchmark_context.py microsoft/vscode#519 pallets/flask#5961
"""
from __future__ import annotations

import re
import sys

import ucp
from ucp_gen import build_package
from ucp_gen.github import fetch_issue_bundle

_REF = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")


def measure(ref: str) -> str:
    match = _REF.match(ref)
    if not match:
        raise SystemExit(f"expected owner/repo#number, got: {ref}")
    bundle = fetch_issue_bundle(match["owner"], match["repo"], int(match["number"]))
    issue = bundle["issue"]

    raw_parts = [issue["title"], issue.get("body") or ""]
    raw_parts += [comment.get("body") or "" for comment in bundle["comments"]]
    raw_parts += [pull.get("body") or "" for pull in bundle["linked_pulls"]]
    raw_tokens = ucp.estimate_tokens("\n\n".join(raw_parts))

    data = build_package(bundle)
    ucp.validate(data)
    pkg = ucp.Package.model_validate(data)
    full_tokens = ucp.estimate_tokens(pkg.render())
    budget_tokens = ucp.estimate_tokens(pkg.render(token_budget=1500))

    fetched = len(bundle["comments"])
    total = issue.get("comments", fetched)
    comments = f"{fetched} of {total}" if total > fetched else str(total)
    return (
        f"| `{ref}` | {comments} | ~{raw_tokens:,} | ~{full_tokens:,} "
        f"| ~{budget_tokens:,} |"
    )


def main(refs: list[str]) -> None:
    if not refs:
        raise SystemExit(__doc__)
    print("| Issue | Comments | Raw thread | UCP | UCP @1500 budget |")
    print("|---|---|---|---|---|")
    for ref in refs:
        print(measure(ref))


if __name__ == "__main__":
    main(sys.argv[1:])
