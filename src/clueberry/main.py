from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import typer
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from clueberry import __version__
from clueberry.analysis import (
    AnalysisError,
    AnalysisResult,
    ClaimAssessment,
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
from clueberry.report import (
    VERDICT_ORDER,
    cited_lines,
    permalink,
    render_markdown,
    summary_line,
    verdict_counts,
    write_report,
)

# Exit codes (also documented in the README).
EXIT_OK = 0
EXIT_USAGE = 2  # invalid URL or option; also Typer's own usage errors
EXIT_GITHUB = 3  # GitHub API: not found, rate limited, network error
EXIT_INSPECTION = 4  # repository could not be fetched or exceeded limits
EXIT_MODEL = 5  # Ollama unreachable, model missing, or claim extraction failed
EXIT_REPORT = 6  # the Markdown report could not be written
EXIT_INTERRUPTED = 130  # Ctrl-C

app = typer.Typer(
    name="clueberry",
    help="Clueberry: a local-first, evidence-driven GitHub issue and PR investigation tool.",
    add_completion=False,
)
console = Console()

_VERDICT_STYLES = {
    Verdict.VERIFIED: "bold green",
    Verdict.PARTIALLY_VERIFIED: "bold yellow",
    Verdict.CONTRADICTED: "bold red",
    Verdict.INCONCLUSIVE: "bold",
}
_MAX_TERMINAL_LINES = 8


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
        "Status: GitHub intake, repository evidence collection, local-model claim "
        "assessment and Markdown reports."
    )


def _fail(label: str, exc: Exception, code: int) -> typer.Exit:
    console.print(f"[bold red]{label}:[/bold red] {escape(str(exc))}")
    return typer.Exit(code=code)


@contextmanager
def _interruptible(what_was_kept: str) -> Iterator[None]:
    # Temporary git workspaces and partial report files are cleaned up by
    # their own context managers as the interrupt unwinds through them.
    try:
        yield
    except KeyboardInterrupt:
        console.print(
            f"\n[yellow]Interrupted.[/yellow] Temporary files were removed; {what_was_kept}"
        )
        raise typer.Exit(code=EXIT_INTERRUPTED) from None


def _fetch_or_exit(url: str) -> GitHubFetchResult:
    try:
        ref = parse_github_issue_or_pr_url(url)
    except InvalidGitHubURLError as exc:
        raise _fail("Invalid URL", exc, EXIT_USAGE) from exc

    settings = Settings()
    try:
        with GitHubClient(token=settings.github_token) as client:
            return client.fetch(ref)
    except GitHubResourceNotFoundError as exc:
        raise _fail("Not found (is the issue/PR public?)", exc, EXIT_GITHUB) from exc
    except GitHubRateLimitError as exc:
        raise _fail("Rate limited", exc, EXIT_GITHUB) from exc
    except GitHubNetworkError as exc:
        raise _fail("Network error", exc, EXIT_GITHUB) from exc
    except GitHubAPIError as exc:
        raise _fail("GitHub API error", exc, EXIT_GITHUB) from exc


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
        raise _fail("Repository inspection failed", exc, EXIT_INSPECTION) from exc


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
    with _interruptible("nothing was saved."):
        target = target_from_fetch_result(_fetch_or_exit(url), extra_terms=term)
        _print_inspection_summary(_inspect_or_exit(target), show_text=show_text)


@app.command()
def analyze(
    url: str = typer.Argument(..., help="A public GitHub issue or pull request URL."),
    term: list[str] = typer.Option(
        [], "--term", "-t", help="Extra search term to look for (repeatable)."
    ),
    output: Path | None = typer.Option(
        None, "--output", "-o", help="Also write a Markdown report to this file."
    ),
) -> None:
    """Extract technical claims from an issue/PR and assess them against repository evidence.

    Uses a local Ollama model (CLUEBERRY_OLLAMA_MODEL, default qwen3:4b).
    Every citation is checked against the collected evidence; verdicts
    without a valid citation are downgraded to INCONCLUSIVE. With qwen3:4b
    each claim takes about 1-3 minutes on an Apple M3 Pro.
    """
    if output is not None and (output.is_dir() or not output.parent.is_dir()):
        console.print(
            f"[bold red]Invalid --output:[/bold red] {escape(str(output))} must be a file "
            "path in an existing directory."
        )
        raise typer.Exit(code=EXIT_USAGE)

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
        _interruptible("no report was written."),
        make_provider(settings.ollama_think) as provider,
        make_provider(settings.ollama_extraction_think) as extraction_provider,
    ):
        try:
            provider.ensure_available()
        except AnalysisError as exc:
            raise _fail("Model unavailable", exc, EXIT_MODEL) from exc

        fetched = _fetch_or_exit(url)
        with console.status("Fetching and inspecting the repository …"):
            inspection = _inspect_or_exit(target_from_fetch_result(fetched, extra_terms=term))
        console.print(
            f"Collected {len(inspection.evidence)} evidence item(s) at "
            f"{inspection.commit_sha[:12]}. Analyzing with {escape(provider.name)} "
            "(this can take a few minutes) …"
        )

        with console.status("Extracting claims …") as status:
            try:
                result = analyze_claims(
                    title=fetched.issue.title,
                    body=fetched.issue.body or "",
                    inspection=inspection,
                    provider=provider,
                    extraction_provider=extraction_provider,
                    kind="pull request" if fetched.kind == "pull_request" else "issue",
                    progress=lambda message: status.update(f"{escape(message)} …"),
                )
            except AnalysisError as exc:
                raise _fail("Analysis failed", exc, EXIT_MODEL) from exc

        _print_analysis(fetched, inspection, result)

        if output is not None:
            content = render_markdown(
                fetched=fetched,
                inspection=inspection,
                analysis=result,
                generated_at=datetime.now(UTC),
            )
            try:
                write_report(output, content)
            except OSError as exc:
                raise _fail("Could not write report", exc, EXIT_REPORT) from exc
            console.print(f"\nReport written to [bold]{escape(str(output))}[/bold]")


def _assessment_panel(assessment: ClaimAssessment, inspection: InspectionResult) -> Panel:
    style = _VERDICT_STYLES[assessment.verdict]
    parts: list[Text] = [
        Text(assessment.claim.text, style="bold"),
        Text.assemble(("Quote: ", "dim"), (assessment.claim.quote, "italic")),
        Text.assemble(("Why: ", "dim"), assessment.explanation),
    ]
    if assessment.model_verdict and assessment.model_verdict is not assessment.verdict:
        parts.append(
            Text(
                f"Model answered {assessment.model_verdict.value}; validation changed it "
                f"to {assessment.verdict.value}.",
                style="yellow",
            )
        )
    for ref in assessment.references:
        parts.append(
            Text.assemble(
                (f"{ref.evidence_id} ", "bold"),
                (f"{ref.category} ", "dim"),
                (ref.location, f"cyan link {permalink(ref)}"),
            )
        )
        lines = cited_lines(inspection, ref)
        for number, line in lines[:_MAX_TERMINAL_LINES]:
            prefix = "        " if number is None else f"  {number:>5} │ "
            parts.append(Text.assemble((prefix, "dim"), line))
        if len(lines) > _MAX_TERMINAL_LINES:
            parts.append(Text(f"        … {len(lines) - _MAX_TERMINAL_LINES} more line(s)", "dim"))
    for note in assessment.validation_notes:
        parts.append(Text(note, style="dim"))
    title = Text.assemble((f" {assessment.claim.id} ", "bold"), (assessment.verdict.value, style))
    return Panel(Group(*parts), title=title, title_align="left", border_style=style)


def _print_analysis(
    fetched: GitHubFetchResult, inspection: InspectionResult, result: AnalysisResult
) -> None:
    # All text from GitHub, the repository and the model is rendered as plain
    # Text objects, so Rich markup inside it is never interpreted.
    kind = "Pull request" if fetched.kind == "pull_request" else "Issue"
    console.print()
    console.print(
        Text.assemble((f"{kind} #{fetched.issue.number}: ", "bold"), (fetched.issue.title, "bold"))
    )
    console.print(Text(f"{result.repository} @ {result.commit_sha} · model {result.model}"))

    counts = verdict_counts(result)
    summary = Text("Result: ", style="bold")
    summary.append(summary_line(result))
    console.print(summary)
    if result.assessments:
        breakdown = Text("  ")
        for verdict in VERDICT_ORDER:
            breakdown.append(f"{verdict.value} {counts[verdict]}", _VERDICT_STYLES[verdict])
            breakdown.append("   ")
        console.print(breakdown)
    for note in result.notes:
        console.print(Text(note, style="yellow"))

    for assessment in result.assessments:
        console.print(_assessment_panel(assessment, inspection))

    if result.rejected_claims:
        console.print(Text(f"Rejected {len(result.rejected_claims)} ungrounded claim(s):"))
        for rejected in result.rejected_claims:
            console.print(Text(f"  - {rejected.text or '(empty)'} ({rejected.reason})", "dim"))


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

    console.print(f"[bold]{kind_label} #{result.issue.number}[/bold]: {escape(result.issue.title)}")
    console.print(f"Repository: {result.owner}/{result.repo}")
    console.print(f"State: {escape(result.issue.state)}  ·  Author: {escape(author)}")
    console.print(f"URL: {escape(result.issue.html_url)}")
    if result.issue.labels:
        console.print(f"Labels: {escape(', '.join(result.issue.labels))}")
    console.print(f"Comments: {len(result.comments)}")

    if result.pull_request is not None:
        pr = result.pull_request
        console.print(
            f"Changes: +{pr.additions}/-{pr.deletions} across {pr.changed_files} file(s) "
            f"({escape(pr.head_ref)} -> {escape(pr.base_ref)})"
        )

    if result.changed_files:
        table = Table(title="Changed files")
        table.add_column("File")
        table.add_column("Status")
        table.add_column("+/-", justify="right")
        for changed_file in result.changed_files:
            table.add_row(
                escape(changed_file.filename),
                escape(changed_file.status),
                f"+{changed_file.additions}/-{changed_file.deletions}",
            )
        console.print(table)

    if result.issue.body:
        body_preview = result.issue.body.strip()
        if len(body_preview) > 300:
            body_preview = body_preview[:300].rstrip() + "…"
        console.print(Panel(Text(body_preview), title="Body", expand=False))


def run() -> None:
    app()


if __name__ == "__main__":
    run()
