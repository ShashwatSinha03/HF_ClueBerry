# Clueberry

Clueberry is a local-first, CLI-first tool for investigating public GitHub
issues and pull requests. It is being built as a hackathon project for
Hacktoberfest 2026 Hack Day Sonipat, by team **Breadcrumbs**.

## Problem statement

Problem 02 — Evidence-Based Open Source Issue and Pull Request Triage.

Maintainers of open-source projects receive issues and pull requests that
contain technical claims (bug reports, "this breaks X", "this fixes Y") of
widely varying quality and accuracy. Clueberry's goal is to help triage
those claims by gathering evidence from the repository itself (source,
docs, tests, history) rather than trusting the claim at face value.

## Current project status

**Foundation stage only.** This repository currently provides the project
skeleton — packaging, CLI entry point, configuration, tests, and CI — and
**does not yet perform any investigation**. In particular, the following are
not implemented yet: GitHub API integration, repository inspection, local
model inference, claim extraction, evidence collection/verification, or
report generation. These will be added in later, separately reviewed
sprints.

## Planned technology stack

- Python 3.12
- [Typer](https://typer.tiangolo.com/) — CLI
- [Rich](https://rich.readthedocs.io/) — terminal output
- [Pydantic](https://docs.pydantic.dev/) / Pydantic Settings — structured
  data and configuration
- [httpx](https://www.python-httpx.org/) — GitHub API communication
  (planned; not yet used)
- [Ollama](https://ollama.com/) running a local open-weight model
  (**Qwen3-4B**, candidate — selected but not yet integrated)
- [pytest](https://docs.pytest.org/) — testing
- [Ruff](https://docs.astral.sh/ruff/) — linting and formatting
- GitHub Actions — CI

No database, web server, or cloud infrastructure is planned. Clueberry is
intended to stay a small, local, CLI tool.

## Installation

Requires Python 3.12.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## CLI usage

```bash
clueberry --help
clueberry --version
clueberry info
```

`clueberry info` prints a short message identifying the project and its
current (foundation-only) status. There is no `analyze` command yet.

## Development

```bash
# Lint
ruff check .

# Run tests
pytest
```

## License

MIT — see [LICENSE](LICENSE).
