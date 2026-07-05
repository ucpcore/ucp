"""CLI: turn a GitHub issue into a validated UCP package.

    ucp-gen github vercel/next.js#12345 -o task.ucp.json
    ucp-gen github owner/repo#42 --since 2026-06-01T00:00:00Z --markdown
"""
from __future__ import annotations

import argparse
import json
import re
import sys

import ucp

from .build import build_package
from .github import GitHubError, fetch_issue_bundle

_REF_RE = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ucp-gen", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gh = sub.add_parser("github", help="generate a UCP from a GitHub issue")
    gh.add_argument("ref", help="issue reference, e.g. owner/repo#123")
    gh.add_argument("-o", "--output", help="write the package to this file (default: stdout)")
    gh.add_argument("--since", help="ISO timestamp: include a context_diff since this moment")
    gh.add_argument("--token", help="GitHub token (default: $GITHUB_TOKEN / $GH_TOKEN)")
    gh.add_argument("--markdown", action="store_true",
                    help="print the canonical LLM rendering instead of JSON")
    gh.add_argument("--token-budget", type=int, default=None,
                    help="token budget for --markdown rendering")

    args = parser.parse_args(argv)

    match = _REF_RE.match(args.ref)
    if not match:
        parser.error(f"expected owner/repo#number, got: {args.ref}")

    try:
        bundle = fetch_issue_bundle(
            match["owner"], match["repo"], int(match["number"]), token=args.token
        )
    except GitHubError as exc:
        print(f"ucp-gen: {exc}", file=sys.stderr)
        return 1

    data = build_package(bundle, since=args.since)

    # The generator must never emit an invalid package.
    ucp.validate(data)
    pkg = ucp.Package.model_validate(data)
    dangling = pkg.verify_references()
    if dangling:
        print(f"ucp-gen: internal error, dangling sources: {dangling}", file=sys.stderr)
        return 2

    if args.markdown:
        out = pkg.render(token_budget=args.token_budget)
    else:
        out = json.dumps(data, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
        est = ucp.estimate_tokens(pkg.render())
        print(f"ucp-gen: wrote {args.output} "
              f"({len(data['sources'])} sources, ~{est} tokens rendered)", file=sys.stderr)
    else:
        print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
