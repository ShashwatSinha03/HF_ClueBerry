from __future__ import annotations

import typer
from rich.console import Console

from clueberry import __version__

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


def run() -> None:
    app()


if __name__ == "__main__":
    run()
