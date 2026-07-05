"""ucp-gen CLI: beautiful terminal front-end for UCP generation.

Decorations (spinners, checkmarks, summaries) go to stderr; stdout stays
pure JSON or Markdown so the output is always safe to pipe.
"""
from __future__ import annotations

import contextlib
import json
import re
import sys
from pathlib import Path
from typing import Optional

import typer

try:  # typer >= 0.16 ships a vendored click as typer._click
    from typer import _click as click
except ImportError:  # pragma: no cover — older typer depends on external click
    import click  # type: ignore[no-redef]
import ucp
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.tree import Tree

from . import __version__
from . import build as github_build
from . import build_jira
from .github import GitHubError, fetch_issue_bundle
from .jira import JiraError, fetch_issue_bundle as fetch_jira_bundle
from .llm import LLMConfig, LLMError, enhance

err = Console(stderr=True, highlight=False)

_GH_REF = re.compile(r"^(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+)#(?P<number>\d+)$")
_JIRA_REF = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$")

app = typer.Typer(
    name="ucp-gen",
    rich_markup_mode="rich",
    add_completion=False,
    no_args_is_help=True,
    help=(
        "📦 Generate [bold]Universal Context Packages[/bold] from real systems.\n\n"
        "Turn a GitHub issue or a Jira ticket into a validated, provenance-backed "
        "context package that any LLM agent can consume.\n\n"
        "Spec: [link=https://ucpcore.org]ucpcore.org[/link] · "
        "[link=https://github.com/ucpcore/ucp]github.com/ucpcore/ucp[/link]"
    ),
    epilog=(
        "[dim]Examples:[/dim]\n\n"
        "  [cyan]ucp-gen github pallets/flask#5961 -o task.ucp.json[/cyan]\n\n"
        "  [cyan]ucp-gen jira PROJ-123 --markdown --token-budget 1500[/cyan]\n\n"
        "  [cyan]ucp-gen github owner/repo#42 --llm[/cyan]   [dim]✨ semantic enhancement[/dim]\n\n"
        "  [cyan]ucp-gen view task.ucp.json[/cyan]"
    ),
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ucp-gen {__version__} (spec {ucp.SPEC_VERSION})")
        raise typer.Exit()


@app.callback()
def _root(
    version: bool = typer.Option(
        False, "--version", "-V", help="Show the version and exit.",
        callback=_version_callback, is_eager=True,
    ),
) -> None:
    pass


def _spin(message: str):
    """Spinner on TTYs, no-op when piped (keeps CI logs clean)."""
    if err.is_terminal:
        return err.status(f"[bold]{message}[/bold]", spinner="dots")
    return contextlib.nullcontext()


def _prompt_if_missing(ref: Optional[str], example: str) -> str:
    if ref:
        return ref
    if err.is_terminal:
        return typer.prompt(f"Issue reference (e.g. {example})")
    raise typer.BadParameter(f"missing issue reference, e.g. {example}")


_LLM_PANEL = "✨ LLM enhancement (optional)"
_OUT_PANEL = "Output"


def _finish(
    data: dict,
    docs: list[dict],
    *,
    llm: bool,
    llm_base_url: Optional[str],
    llm_api_key: Optional[str],
    llm_model: Optional[str],
    output: Optional[Path],
    markdown: bool,
    token_budget: Optional[int],
) -> None:
    if llm:
        config = LLMConfig.from_env(
            base_url=llm_base_url, api_key=llm_api_key, model=llm_model
        )
        try:
            with _spin(f"✨ Enhancing with {config.model}…"):
                data = enhance(data, docs, config)
            err.print(
                f"[green]✓[/green] enhanced with [bold]{config.model}[/bold]"
                " — summary, salience, decisions from prose"
            )
        except LLMError as exc:
            err.print(f"[yellow]⚠[/yellow] {exc} — keeping the structure-only package")

    # The generator must never emit an invalid package.
    ucp.validate(data)
    pkg = ucp.Package.model_validate(data)
    dangling = pkg.verify_references()
    if dangling:
        err.print(f"[red]✗[/red] internal error, dangling sources: {dangling}")
        raise typer.Exit(2)
    err.print(
        f"[green]✓[/green] valid [bold]{'+'.join(data.get('profiles') or ['ucp-core'])}[/bold]"
        f" package — {len(data['sources'])} sources, sha256-hashed"
    )

    text = (
        pkg.render(token_budget=token_budget)
        if markdown
        else json.dumps(data, indent=2, ensure_ascii=False)
    )

    if output:
        output.write_text(text + "\n", encoding="utf-8")
        est = ucp.estimate_tokens(pkg.render())
        tree = Tree(f"📦 wrote [bold cyan]{output}[/bold cyan]")
        tree.add(f"[bold]{data['entity']['title']}[/bold]")
        tree.add(f"claims      {len(data.get('must_know') or [])} must-know")
        accepted = sum(1 for d in data.get("decisions") or [] if d.get("status") == "accepted")
        tree.add(f"decisions   {len(data.get('decisions') or [])} ({accepted} accepted)")
        tree.add(f"conflicts   {len(data.get('conflicts') or [])}")
        tree.add(f"sources     {len(data['sources'])}")
        tree.add(f"tokens      ~{est:,} rendered")
        err.print(tree)
    elif markdown and sys.stdout.isatty():
        Console().print(Markdown(text))
    else:
        print(text)


def _llm_options():
    """Shared --llm* option declarations (typer needs them per command)."""
    return dict(
        llm=typer.Option(False, "--llm", help="Enhance with an OpenAI-compatible model.",
                         rich_help_panel=_LLM_PANEL),
        llm_base_url=typer.Option(None, help="Endpoint (default: $UCP_LLM_BASE_URL or api.openai.com).",
                                  rich_help_panel=_LLM_PANEL),
        llm_api_key=typer.Option(None, help="Key (default: $UCP_LLM_API_KEY / $OPENAI_API_KEY).",
                                 rich_help_panel=_LLM_PANEL),
        llm_model=typer.Option(None, help="Model (default: $UCP_LLM_MODEL or gpt-4o-mini).",
                               rich_help_panel=_LLM_PANEL),
    )


@app.command(help="🐙 Generate a UCP from a [bold]GitHub[/bold] issue.")
def github(
    ref: Optional[str] = typer.Argument(None, metavar="OWNER/REPO#N",
                                        help="e.g. [cyan]pallets/flask#5961[/cyan]"),
    token: Optional[str] = typer.Option(None, help="GitHub token (default: $GITHUB_TOKEN / $GH_TOKEN)."),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
                                          help="Write the package to this file.",
                                          rich_help_panel=_OUT_PANEL),
    since: Optional[str] = typer.Option(None, help="ISO timestamp: add a context_diff since this moment."),
    markdown: bool = typer.Option(False, "--markdown", "-m",
                                  help="Print the canonical LLM rendering instead of JSON.",
                                  rich_help_panel=_OUT_PANEL),
    token_budget: Optional[int] = typer.Option(None, help="Token budget for --markdown rendering.",
                                               rich_help_panel=_OUT_PANEL),
    llm: bool = _llm_options()["llm"],
    llm_base_url: Optional[str] = _llm_options()["llm_base_url"],
    llm_api_key: Optional[str] = _llm_options()["llm_api_key"],
    llm_model: Optional[str] = _llm_options()["llm_model"],
) -> None:
    ref = _prompt_if_missing(ref, "owner/repo#123")
    match = _GH_REF.match(ref)
    if not match:
        raise typer.BadParameter(f"expected owner/repo#number, got: {ref}")
    try:
        with _spin(f"🐙 Fetching {ref} from GitHub…"):
            bundle = fetch_issue_bundle(
                match["owner"], match["repo"], int(match["number"]), token=token
            )
    except GitHubError as exc:
        err.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(1)
    err.print(
        f"[green]✓[/green] [bold]{ref}[/bold] — issue"
        f" + {len(bundle['comments'])} comments"
        f" + {len(bundle['linked_pulls'])} linked PRs"
    )
    data = github_build.build_package(bundle, since=since)
    docs = github_build.llm_docs(bundle, data["generated_at"])
    _finish(data, docs, llm=llm, llm_base_url=llm_base_url, llm_api_key=llm_api_key,
            llm_model=llm_model, output=output, markdown=markdown, token_budget=token_budget)


@app.command(help="🎫 Generate a UCP from a [bold]Jira[/bold] ticket.")
def jira(
    ref: Optional[str] = typer.Argument(None, metavar="KEY",
                                        help="e.g. [cyan]PROJ-123[/cyan]"),
    base_url: Optional[str] = typer.Option(None, help="Jira base URL (default: $JIRA_BASE_URL)."),
    email: Optional[str] = typer.Option(None, help="Jira Cloud email for Basic auth (default: $JIRA_EMAIL)."),
    token: Optional[str] = typer.Option(None, help="API token or PAT (default: $JIRA_API_TOKEN)."),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
                                          help="Write the package to this file.",
                                          rich_help_panel=_OUT_PANEL),
    since: Optional[str] = typer.Option(None, help="ISO timestamp: add a context_diff since this moment."),
    markdown: bool = typer.Option(False, "--markdown", "-m",
                                  help="Print the canonical LLM rendering instead of JSON.",
                                  rich_help_panel=_OUT_PANEL),
    token_budget: Optional[int] = typer.Option(None, help="Token budget for --markdown rendering.",
                                               rich_help_panel=_OUT_PANEL),
    llm: bool = _llm_options()["llm"],
    llm_base_url: Optional[str] = _llm_options()["llm_base_url"],
    llm_api_key: Optional[str] = _llm_options()["llm_api_key"],
    llm_model: Optional[str] = _llm_options()["llm_model"],
) -> None:
    ref = _prompt_if_missing(ref, "PROJ-123")
    if not _JIRA_REF.match(ref):
        raise typer.BadParameter(f"expected a Jira key like PROJ-123, got: {ref}")
    try:
        with _spin(f"🎫 Fetching {ref} from Jira…"):
            bundle = fetch_jira_bundle(ref, base_url=base_url, email=email, token=token)
    except JiraError as exc:
        err.print(f"[red]✗[/red] {exc}")
        raise typer.Exit(1)
    err.print(f"[green]✓[/green] [bold]{ref}[/bold] — issue + {len(bundle['comments'])} comments")
    data = build_jira.build_jira_package(bundle, since=since)
    docs = build_jira.llm_docs(bundle, data["generated_at"])
    _finish(data, docs, llm=llm, llm_base_url=llm_base_url, llm_api_key=llm_api_key,
            llm_model=llm_model, output=output, markdown=markdown, token_budget=token_budget)


@app.command(help="👀 Pretty-print a [bold].ucp.json[/bold] package in the terminal.")
def view(
    file: Path = typer.Argument(..., exists=True, readable=True, metavar="FILE.ucp.json"),
    token_budget: Optional[int] = typer.Option(None, help="Render under this token budget."),
) -> None:
    try:
        pkg = ucp.load(file)
    except ucp.UCPValidationError as exc:
        err.print(f"[red]✗[/red] not a valid UCP package: {exc}")
        raise typer.Exit(1)

    out = Console()
    entity = pkg.entity
    meta = (
        f"[bold]{entity.title}[/bold]\n"
        f"[dim]{entity.ref.system}/{entity.ref.type}[/dim] {entity.ref.id}"
        + (f" · [cyan]{entity.status}[/cyan]" if entity.status else "")
        + f"\n[dim]generated {pkg.generated_at:%Y-%m-%d %H:%M} UTC"
        f" by {pkg.generator.name} {pkg.generator.version or ''}"
        f" · {len(pkg.sources)} sources[/dim]"
    )
    out.print(Panel(meta, title="📦 Universal Context Package", border_style="cyan"))
    out.print(Markdown(pkg.render(token_budget=token_budget)))


def main(argv: Optional[list[str]] = None) -> int:
    try:
        result = app(args=argv, standalone_mode=False)
        return int(result) if isinstance(result, int) else 0
    except click.exceptions.Exit as exc:  # typer.Exit
        return int(exc.exit_code)
    except click.exceptions.Abort:
        err.print("[dim]aborted[/dim]")
        return 130
    except click.exceptions.ClickException as exc:
        err.print(f"[red]✗[/red] {exc.format_message()}")
        raise SystemExit(2)


if __name__ == "__main__":
    raise SystemExit(main())
