from __future__ import annotations

import typer
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from clueberry import __version__
from clueberry.analysis import (
    AnalysisError,
    AnalysisResult,
    OllamaProvider,
    Verdict,
    analyze_claims,
)
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
from clueberry.investigation import (
    InspectionError,
    InspectionResult,
    InvestigationTarget,
    inspect_repository,
    target_from_fetch_result,
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
    """Clueberry: evidence-driven GitHub issue and PR investigation."""


@app.command()
def info() -> None:
    """Print a short message identifying the project and its current status."""
    console.print("[bold]Clueberry[/bold]")
    console.print("Evidence-driven GitHub issue and pull request investigation tool.")
    console.print(
        "Status: GitHub intake, repository evidence collection and local-model claim "
        "assessment work; investigation reports are not yet implemented."
    )


def _fetch_or_exit(url: str) -> GitHubFetchResult:
    try:
        ref = parse_github_issue_or_pr_url(url)
    except InvalidGitHubURLError as exc:
        console.print(f"[bold red]Invalid URL:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc

    settings = Settings()
    try:
        with GitHubClient(token=settings.github_token) as client:
            return client.fetch(ref)
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


@app.command()
def fetch(
    url: str = typer.Argument(..., help="A public GitHub issue or pull request URL."),
) -> None:
    """Fetch a public GitHub issue or pull request and print a concise summary."""
    _print_fetch_summary(_fetch_or_exit(url))


@app.command("inspect")
def inspect_command(
    url: str = typer.Argument(..., help="A public GitHub issue or pull request URL."),
    term: list[str] = typer.Option(
        [], "--term", "-t", help="Extra search term to look for (repeatable)."
    ),
    show_text: bool = typer.Option(False, "--show-text", help="Print each evidence snippet."),
) -> None:
    """Inspect the repository behind an issue/PR and list the evidence collected.

    Repository code is never executed; files are read from a shallow,
    temporary git fetch that is deleted afterwards.
    """
    target = target_from_fetch_result(_fetch_or_exit(url), extra_terms=term)
    _print_inspection_summary(_inspect_or_exit(target), show_text=show_text)


def _inspect_or_exit(target: InvestigationTarget) -> InspectionResult:
    console.print(f"Inspecting {target.repository} at {target.revision} …")
    try:
        return inspect_repository(
            target.clone_url,
            target.repository,
            revision=target.revision,
            changed_paths=target.changed_paths,
            search_terms=target.search_terms,
        )
    except InspectionError as exc:
        console.print(f"[bold red]Inspection failed:[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def analyze(
    url: str = typer.Argument(..., help="A public GitHub issue or pull request URL."),
    term: list[str] = typer.Option(
        [], "--term", "-t", help="Extra search term to look for (repeatable)."
    ),
) -> None:
    """Extract technical claims from an issue/PR and assess them against repository evidence.

    Uses a local Ollama model (CLUEBERRY_OLLAMA_MODEL, default qwen3:4b).
    Every citation is checked against the collected evidence; verdicts
    without a valid citation are downgraded to INCONCLUSIVE. With qwen3:4b
    each claim takes about 1-3 minutes on an Apple M3 Pro.
    """
    settings = Settings()

    def make_provider(think: bool | None) -> OllamaProvider:
        return OllamaProvider(
            settings.ollama_model,
            base_url=settings.ollama_base_url,
            timeout=settings.ollama_timeout_seconds,
            num_ctx=settings.ollama_num_ctx,
            think=think,
        )

    with (
        make_provider(settings.ollama_think) as provider,
        make_provider(settings.ollama_extraction_think) as extraction_provider,
    ):
        try:
            provider.ensure_available()
        except AnalysisError as exc:
            console.print(f"[bold red]Model unavailable:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

        fetched = _fetch_or_exit(url)
        inspection = _inspect_or_exit(target_from_fetch_result(fetched, extra_terms=term))
        console.print(
            f"Found {len(inspection.evidence)} evidence item(s). "
            f"Analyzing claims with {provider.name} …"
        )
        try:
            result = analyze_claims(
                title=fetched.issue.title,
                body=fetched.issue.body or "",
                inspection=inspection,
                provider=provider,
                extraction_provider=extraction_provider,
                kind="pull request" if fetched.kind == "pull_request" else "issue",
            )
        except AnalysisError as exc:
            console.print(f"[bold red]Analysis failed:[/bold red] {exc}")
            raise typer.Exit(code=1) from exc

    _print_analysis(result)


_VERDICT_STYLES = {
    Verdict.VERIFIED: "bold green",
    Verdict.PARTIALLY_VERIFIED: "bold yellow",
    Verdict.CONTRADICTED: "bold red",
    Verdict.INCONCLUSIVE: "bold",
}


def _print_analysis(result: AnalysisResult) -> None:
    # Claims, explanations and notes derive from untrusted input: escape them.
    console.print(f"[bold]{escape(result.repository)}[/bold] @ {result.commit_sha}")
    console.print(f"Model: {escape(result.model)}")
    for note in result.notes:
        console.print(f"[yellow]{escape(note)}[/yellow]")

    for assessment in result.assessments:
        style = _VERDICT_STYLES[assessment.verdict]
        console.print()
        console.print(
            f"[{style}]{assessment.verdict.value}[/{style}]  "
            f"{assessment.claim.id}: {escape(assessment.claim.text)}"
        )
        console.print(f"  Quote: {escape(assessment.claim.quote)}")
        console.print(f"  Why: {escape(assessment.explanation)}")
        for ref in assessment.references:
            console.print(f"  Evidence {ref.evidence_id}: {escape(ref.location)}")
        for note in assessment.validation_notes:
            console.print(f"  [dim]{escape(note)}[/dim]")

    if result.rejected_claims:
        console.print()
        console.print(f"Rejected {len(result.rejected_claims)} ungrounded claim(s):")
        for rejected in result.rejected_claims:
            console.print(f"  - {escape(rejected.text)} ({escape(rejected.reason)})")


def _print_inspection_summary(result: InspectionResult, *, show_text: bool) -> None:
    # Paths, terms and file text are untrusted: escape them so Rich markup in
    # repository content can't restyle or hide output.
    console.print(f"[bold]{escape(result.repository)}[/bold] @ {result.commit_sha}")
    console.print(f"Search terms: {escape(', '.join(result.search_terms)) or '(none)'}")
    console.print(
        f"Files: {result.files_in_tree} in tree, {result.files_eligible} eligible, "
        f"{result.files_inspected} inspected"
    )
    if result.skipped:
        console.print(
            "Skipped: " + ", ".join(f"{reason}={n}" for reason, n in result.skipped.items())
        )
    if result.truncated:
        console.print("[yellow]Limits reached; results were truncated.[/yellow]")

    table = Table(title=f"Evidence ({len(result.evidence)})")
    table.add_column("Category")
    table.add_column("Location")
    table.add_column("Reason")
    for item in result.evidence:
        table.add_row(item.category, escape(item.location), escape(item.reason))
    console.print(table)

    if show_text:
        for item in result.evidence:
            console.print(Panel(Text(item.text), title=escape(item.location), expand=False))


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
