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

**Repository investigation stage.** Clueberry can fetch a public GitHub
issue or pull request (`clueberry fetch <url>`) and collect traceable
evidence from the repository behind it (`clueberry inspect <url>`): source,
documentation, test snippets and recent file history, each tied to an exact
commit SHA, file path and line range.

It **does not yet assess anything**. Local model inference, claim
extraction, verdicts and final reports are not implemented; they will be
added in later, separately reviewed sprints.

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
clueberry inspect <github-issue-or-pr-url> [--term NAME ...] [--show-text]
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

`clueberry inspect` fetches the same issue/PR, then shallow-fetches the
repository (the PR's exact head commit, or the default branch for an
issue) and lists the evidence it collected. Files changed by a PR, file
paths mentioned in the issue/PR, related tests and the README are looked at
first; other files are searched for code-like terms (identifiers, dotted
names, paths) taken from the title and body, plus any `--term` you add.
`--show-text` prints each snippet.

```bash
clueberry inspect https://github.com/psf/requests/issues/7611
```

Repository content is treated as untrusted:

- Only `https://github.com/<owner>/<repo>` is fetched, at `HEAD`, a full
  commit SHA, or a PR head ref — never an arbitrary branch name.
- Nothing is checked out or executed. Files are read straight from git's
  object database in a temporary directory that is always deleted.
- Symlinks, submodules, binary, generated, dependency-directory and
  oversized files are skipped.
- Git runs with a scrubbed environment (no tokens, credentials or user git
  config), no hooks, no credential helpers, and per-command timeouts.
- Fetch depth, tree size, file count, file size, total bytes read and
  evidence count are bounded (see `InspectionLimits`). Repository size is
  only checked *after* the fetch completes; the download itself is
  currently bounded only by the git command timeout (120 s by default).

For pull requests, Clueberry inspects the **head snapshot** of the PR — the
repository as it looks at the PR's head commit — not the base-to-head diff.
Changed files are prioritized, but a "(file overview)" snippet is simply the
first lines of that file at the head commit and may not include any of the
lines the PR actually changed. File history is limited to the shallow fetch
depth, and the oldest fetched commit is never reported as changing a file
(git can't tell what it changed without its parent).

There is no `analyze` command yet — Clueberry collects evidence but does
not extract claims or assess them.

## Development

```bash
# Lint
ruff check .

# Run tests
pytest
```

## License

MIT — see [LICENSE](LICENSE).
