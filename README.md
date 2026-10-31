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

**Evidence analysis stage.** Clueberry can fetch a public GitHub issue or
pull request (`clueberry fetch <url>`), collect traceable evidence from the
repository behind it (`clueberry inspect <url>`), and use a local Ollama
model to extract technical claims and assess each one against that evidence
(`clueberry analyze <url>`).

Investigation reports (saved JSON/Markdown output and examples) are not
implemented yet; they will be added in a later, separately reviewed sprint.

## Planned technology stack

- Python 3.12
- [Typer](https://typer.tiangolo.com/) — CLI
- [Rich](https://rich.readthedocs.io/) — terminal output
- [Pydantic](https://docs.pydantic.dev/) / Pydantic Settings — structured
  data and configuration
- [httpx](https://www.python-httpx.org/) — GitHub REST API communication
- [Ollama](https://ollama.com/) running a local open-weight model
  (default **Qwen3-4B**, configurable)
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

### Claim analysis

`clueberry analyze` runs `inspect`, then asks a local model to extract
individual, testable technical claims from the issue/PR title and body and
to assess each one against the collected evidence. Each claim gets one
verdict:

| Verdict | Meaning |
|---|---|
| `VERIFIED` | The evidence directly and fully supports the claim. |
| `PARTIALLY_VERIFIED` | The evidence supports part of the claim, or only with caveats. |
| `CONTRADICTED` | The evidence directly shows the claim is false. |
| `INCONCLUSIVE` | The evidence is missing, unrelated or insufficient. |

It needs [Ollama](https://ollama.com/) running locally with the model pulled:

```bash
ollama pull qwen3:4b
clueberry analyze https://github.com/psf/requests/issues/7611
```

Model settings (environment variables):

| Variable | Default |
|---|---|
| `CLUEBERRY_OLLAMA_MODEL` | `qwen3:4b` |
| `CLUEBERRY_OLLAMA_BASE_URL` | `http://localhost:11434` |
| `CLUEBERRY_OLLAMA_TIMEOUT_SECONDS` | `300` (per model call) |
| `CLUEBERRY_OLLAMA_NUM_CTX` | `16384` |
| `CLUEBERRY_OLLAMA_THINK` | unset — thinking for claim *assessment* (model default; Qwen3: on) |
| `CLUEBERRY_OLLAMA_EXTRACTION_THINK` | `false` — thinking for claim *extraction* |

#### Tested models

Measured on an Apple M3 Pro (18 GB RAM), Ollama 0.40.13, against real
`psf/requests` issues #7611 and #7600 at commit `3c7baaa` plus five
hand-written claims with known answers.

How the numbers were obtained:

- **Live:** every model answer and every latency below came from real
  Ollama calls. Verdicts for the hand-written claims were produced live
  with each setting.
- **Replayed:** after the live runs, two validation rules were added (the
  citation relevance check and backtick-tolerant quote grounding). Their
  effect was measured by replaying the saved live answers through the
  updated code, not by a fresh end-to-end run. Replayed figures are marked.
- **Default timings:** the default setting's latencies come from a later
  live run that was stopped early, after issue #7611 and one claim of
  #7600.

| Model / setting | Hand-written claims correct | Latency per call | Status |
|---|---|---|---|
| `qwen3:4b`, extraction thinking off + assessment thinking on (**default**) | 5/5, each citing the exact supporting line (live; unchanged on replay) | extraction 10–12 s; assessment 69–156 s, one > 180 s (live) | Supported |
| `qwen3:4b`, thinking on for both | 5/5 (live) | extraction exceeded 180 s on both issues (live) | Not recommended |
| `qwen3:4b`, thinking off for both (`CLUEBERRY_OLLAMA_THINK=false`) | 4/5, one `VERIFIED` that should not be (live; unchanged on replay) | 7–14 s (live) | Fast but less accurate |
| `gemma3:1b` | 1/5 live; 2/5 on replay, because the relevance check downgrades one invented "support" | 1–4 s (live) | Not suitable: paraphrases quotes (claims rejected) and answers `PARTIALLY_VERIFIED` regardless of evidence |

On replay, backtick-tolerant grounding kept all 3 valid claims the model
extracted from issue #7611, up from 1 of 3. The relevance check rejected
none of `qwen3:4b`'s correct citations and 7 irrelevant `gemma3:1b`
citations.

The default timeout is **300 s per model call** because one live
thinking-mode assessment exceeded the earlier 180 s limit. A call that
still times out makes only that claim `INCONCLUSIVE`.

With the default, `analyze` takes roughly 1–3 minutes per claim. Thinking
is on for assessment because it was the only setting that got every
benchmark verdict right; it is off for extraction because thinking made
extraction time out. Models without thinking support work with the
defaults (`CLUEBERRY_OLLAMA_THINK=true` would make Ollama reject them).

The model only *proposes*; deterministic code decides what is accepted:

- A claim is kept only if its quote appears verbatim in the issue/PR text
  (ignoring whitespace, case, quote marks and markdown backticks).
- Every citation must name an evidence item the model was actually shown,
  with the same path, a line range inside that item (no lines for history
  items), and — if a commit is cited — the inspected commit. The cited
  lines must also share at least one meaningful word or number with the
  claim, which rejects clearly unrelated citations. Invalid citations are
  discarded.
- Any verdict other than `INCONCLUSIVE` that is left without a valid
  citation is downgraded to `INCONCLUSIVE`. The model's original answer is
  kept as `model_verdict`.
- Finished results are re-checked independently against the collected
  evidence before they are returned.
- Issue/PR text and repository content are passed to the model inside
  markers built from a random per-request nonce, with instructions to treat
  them strictly as data. Control characters are stripped, inputs are
  truncated, and requests use structured (JSON schema) output at
  temperature 0. Proxy environment variables are ignored.
- If the model can't be reached or isn't installed, `analyze` stops before
  doing any work. A timeout or malformed answer for one claim makes only
  that claim `INCONCLUSIVE`.

Limitations: validation proves a citation *exists* in the collected
evidence and shares a term with the claim, not that it *supports* the
claim — a model can still cite a loosely related line or choose the wrong
verdict (seen with thinking off, and constantly with `gemma3:1b`). Accuracy
was measured on a small benchmark (five hand-written claims, two real
issues), not a large evaluation; assessment with thinking on was not
measured end-to-end on issue #7600 because one claim timed out under the
previous 180 s limit. A claim can be grounded in
any sentence of the issue text, including one planted by a
prompt-injection attempt; such claims still need valid citations to get a
non-`INCONCLUSIVE` verdict. Verdicts depend on model quality and on what
Sprint 2 evidence collection found (PR head snapshot only).

## Development

```bash
# Lint
ruff check .

# Run tests
pytest
```

## License

MIT — see [LICENSE](LICENSE).
