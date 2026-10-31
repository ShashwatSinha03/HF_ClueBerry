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

**GitHub intake stage.** Clueberry can fetch and summarize a public GitHub
issue or pull request (`clueberry fetch <url>`), but it **does not yet
investigate anything**. In particular, the following are not implemented
yet: cloning or inspecting repository source code, local model inference,
claim extraction, evidence collection/verification, or report generation.
These will be added in later, separately reviewed sprints.

## Planned technology stack

- Python 3.12
- [Typer](https://typer.tiangolo.com/) — CLI
- [Rich](https://rich.readthedocs.io/) — terminal output
- [Pydantic](https://docs.pydantic.dev/) / Pydantic Settings — structured
  data and configuration
- [httpx](https://www.python-httpx.org/) — GitHub REST API communication
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
clueberry fetch <github-issue-or-pr-url>
```

`clueberry info` prints a short message identifying the project and its
current status.

`clueberry fetch` accepts a public GitHub issue or pull request URL
(`https://github.com/<owner>/<repo>/issues/<number>` or
`.../pull/<number>`), retrieves its metadata, body, and comments (plus,
for pull requests, the changed-file list and line counts) via the public
GitHub REST API, and prints a concise summary. For example:

```bash
clueberry fetch https://github.com/octocat/Hello-World/issues/1
```

Unauthenticated access works for public issues/PRs but is subject to
GitHub's lower rate limit. To use a higher limit, set a personal access
token as an environment variable:

```bash
export CLUEBERRY_GITHUB_TOKEN=ghp_your_token_here
```

There is no `analyze` command yet — `fetch` only retrieves and displays
GitHub data; it does not inspect repository source code or assess any
claims.

## Development

```bash
# Lint
ruff check .

# Run tests
pytest
```

## License

MIT — see [LICENSE](LICENSE).
