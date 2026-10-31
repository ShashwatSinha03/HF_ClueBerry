from __future__ import annotations

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from clueberry import __version__
from clueberry.config import Settings
from clueberry.github import (
    GitHubAPIError,
    GitHubClient,
    GitHubFetchResult,
    GitHubNetworkError,
    GitHubRateLimitError,
    GitHubResourceNotFoundError,
    InvalidGitHubURLError,
    parse_github_issue_or_pr_url,
)

app = typer.Typer(
    name="clueberry",
    help="Clueberry: a local-first, evidence-driven GitHub issue and PR investigation tool.",
    add_completion=False,
)
console = Console()


def _print_version(show: bool) -> None:
    if show:
        console.print(f"clueberry {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def callback(
    version: bool = typer.Option(
        False,
        "--version",
        help="Show the Clueberry version and exit.",
        callback=_print_version,
        is_eager=True,
    ),
) -> None:
    """Clueberry: evidence-driven GitHub issue and PR investigation (foundation only)."""


@app.command()
def info() -> None:
    """Print a short message identifying the project and its current status."""
    console.print("[bold]Clueberry[/bold]")
    console.print("Evidence-driven GitHub issue and pull request investigation tool.")
    console.print(
        "Status: project foundation only — investigation features are not yet implemented."
    )


@app.command()
def fetch(
    url: str = typer.Argument(..., help="A public GitHub issue or pull request URL."),
) -> None:
    """Fetch a public GitHub issue or pull request and print a concise summary."""
    try:
        ref = parse_github_issue_or_pr_url(url)
    except InvalidGitHubURLError as exc:
        console.print(f"[bold red]Invalid URL:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    settings = Settings()
    try:
        with GitHubClient(token=settings.github_token) as client:
            result = client.fetch(ref)
    except GitHubResourceNotFoundError as exc:
        console.print(f"[bold red]Not found:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    except GitHubRateLimitError as exc:
        console.print(f"[bold red]Rate limited:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    except GitHubNetworkError as exc:
        console.print(f"[bold red]Network error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc
    except GitHubAPIError as exc:
        console.print(f"[bold red]GitHub API error:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    _print_fetch_summary(result)


def _print_fetch_summary(result: GitHubFetchResult) -> None:
    kind_label = "Pull Request" if result.kind == "pull_request" else "Issue"
    author = result.issue.user.login if result.issue.user else "unknown"

    console.print(f"[bold]{kind_label} #{result.issue.number}[/bold]: {result.issue.title}")
    console.print(f"Repository: {result.owner}/{result.repo}")
    console.print(f"State: {result.issue.state}  ·  Author: {author}")
    console.print(f"URL: {result.issue.html_url}")
    if result.issue.labels:
        console.print(f"Labels: {', '.join(result.issue.labels)}")
    console.print(f"Comments: {len(result.comments)}")

    if result.pull_request is not None:
        pr = result.pull_request
        console.print(
            f"Changes: +{pr.additions}/-{pr.deletions} across {pr.changed_files} file(s) "
            f"({pr.head_ref} -> {pr.base_ref})"
        )

    if result.changed_files:
        table = Table(title="Changed files")
        table.add_column("File")
        table.add_column("Status")
        table.add_column("+/-", justify="right")
        for changed_file in result.changed_files:
            table.add_row(
                changed_file.filename,
                changed_file.status,
                f"+{changed_file.additions}/-{changed_file.deletions}",
            )
        console.print(table)

    if result.issue.body:
        body_preview = result.issue.body.strip()
        if len(body_preview) > 300:
            body_preview = body_preview[:300].rstrip() + "…"
        console.print(Panel(body_preview, title="Body", expand=False))


def run() -> None:
    app()


if __name__ == "__main__":
    run()
