"""CLI: turn a GitHub issue or a Jira ticket into a validated UCP package.

    ucp-gen github vercel/next.js#12345 -o task.ucp.json
    ucp-gen jira PROJ-123 --base-url https://co.atlassian.net -o task.ucp.json
    ucp-gen github owner/repo#42 --llm --markdown --token-budget 1500
"""
from __future__ import annotations

import argparse
import json
import re
import sys

import ucp

from . import build as github_build
from . import build_jira
from .github import GitHubError, fetch_issue_bundle
from .jira import JiraError, fetch_issue_bundle as fetch_jira_bundle
from .llm import LLMConfig, LLMError, enhance

_GH_REF = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")
_JIRA_REF = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--output", help="write the package to this file (default: stdout)")
    parser.add_argument("--since", help="ISO timestamp: include a context_diff since this moment")
    parser.add_argument("--markdown", action="store_true",
                        help="print the canonical LLM rendering instead of JSON")
    parser.add_argument("--token-budget", type=int, default=None,
                        help="token budget for --markdown rendering")
    llm = parser.add_argument_group("LLM enhancement (optional)")
    llm.add_argument("--llm", action="store_true",
                     help="enhance with an OpenAI-compatible model: real summary, "
                          "semantic salience, decisions/conflicts from prose")
    llm.add_argument("--llm-base-url", help="endpoint base URL (default: $UCP_LLM_BASE_URL "
                                            "or https://api.openai.com/v1)")
    llm.add_argument("--llm-api-key", help="API key (default: $UCP_LLM_API_KEY / $OPENAI_API_KEY)")
    llm.add_argument("--llm-model", help="model name (default: $UCP_LLM_MODEL or gpt-4o-mini)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ucp-gen", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    gh = sub.add_parser("github", help="generate a UCP from a GitHub issue")
    gh.add_argument("ref", help="issue reference, e.g. owner/repo#123")
    gh.add_argument("--token", help="GitHub token (default: $GITHUB_TOKEN / $GH_TOKEN)")
    _add_common(gh)

    jr = sub.add_parser("jira", help="generate a UCP from a Jira issue")
    jr.add_argument("ref", help="issue key, e.g. PROJ-123")
    jr.add_argument("--base-url", help="Jira base URL (default: $JIRA_BASE_URL)")
    jr.add_argument("--email", help="Jira Cloud email for Basic auth (default: $JIRA_EMAIL)")
    jr.add_argument("--token", help="API token or PAT (default: $JIRA_API_TOKEN)")
    _add_common(jr)

    args = parser.parse_args(argv)

    try:
        if args.command == "github":
            match = _GH_REF.match(args.ref)
            if not match:
                gh.error(f"expected owner/repo#number, got: {args.ref}")
            bundle = fetch_issue_bundle(
                match["owner"], match["repo"], int(match["number"]), token=args.token
            )
            data = github_build.build_package(bundle, since=args.since)
            docs = github_build.llm_docs(bundle, data["generated_at"])
        else:
            if not _JIRA_REF.match(args.ref):
                jr.error(f"expected a Jira key like PROJ-123, got: {args.ref}")
            bundle = fetch_jira_bundle(
                args.ref, base_url=args.base_url, email=args.email, token=args.token
            )
            data = build_jira.build_jira_package(bundle, since=args.since)
            docs = build_jira.llm_docs(bundle, data["generated_at"])
    except (GitHubError, JiraError) as exc:
        print(f"ucp-gen: {exc}", file=sys.stderr)
        return 1

    if args.llm:
        try:
            config = LLMConfig.from_env(
                base_url=args.llm_base_url, api_key=args.llm_api_key, model=args.llm_model
            )
            data = enhance(data, docs, config)
        except LLMError as exc:
            print(f"ucp-gen: warning: {exc}; keeping the structure-only package",
                  file=sys.stderr)

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
