# Clueberry

Clueberry is a local-first command-line tool that checks the technical
claims in a public GitHub issue or pull request against the repository's
own code, tests, documentation and history, and reports which claims the
evidence supports.

It was built for **Problem 02 — Evidence-Based Open Source Issue and Pull
Request Triage** at Hacktoberfest 2026 Hack Day Sonipat by team
**Breadcrumbs**.

## What it does

```
GitHub issue / PR URL
   │  1. Intake      GitHub REST API: title, body, comments, PR changed files
   ▼
   │  2. Inspect     shallow git fetch of the exact commit, read-only, sandboxed;
   │                 collects source / test / documentation snippets and file history
   ▼
   │  3. Analyze     local Ollama model (default qwen3:4b) extracts testable claims
   │                 and assesses each against the evidence
   ▼
   │  4. Validate    deterministic checks on every claim quote and citation
   ▼
Verdicts in the terminal, plus an optional Markdown report
```

Each claim gets one verdict:

| Verdict | Meaning |
|---|---|
| `VERIFIED` | The evidence directly and fully supports the claim. |
| `PARTIALLY_VERIFIED` | The evidence supports part of the claim, or only with caveats. |
| `CONTRADICTED` | The evidence directly shows the claim is false. |
| `INCONCLUSIVE` | The evidence is missing, unrelated or insufficient. |

Every verdict other than `INCONCLUSIVE` is backed by at least one citation
that points at an exact file, line range and commit, with a GitHub
permalink.

## Quick demo

```bash
# 1. Install (Python 3.12)
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 2. Start Ollama and pull the default model (~2.5 GB, one-time)
ollama serve          # skip if the Ollama app is already running
ollama pull qwen3:4b

# 3. Analyze a real issue and save a report
clueberry analyze https://github.com/psf/requests/issues/7611 --output report.md
```

With the default model this takes a few minutes (roughly 1–3 minutes per
claim on an Apple M3 Pro). A real example run, with the exact command,
terminal output and report, is in [`examples/requests-7611/`](examples/requests-7611/).

## Installation

Requires Python 3.12 and `git`. For `analyze`, you also need
[Ollama](https://ollama.com/download) running locally.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
clueberry --version
```

### Ollama setup

1. Install Ollama from <https://ollama.com/download> and make sure it is
   running (`ollama serve`, or the desktop app).
2. Pull the default model: `ollama pull qwen3:4b`.
3. Check it: `ollama list` should show `qwen3:4b`.

If Ollama isn't reachable or the model isn't installed, `clueberry analyze`
stops immediately with a message saying what to run, before doing any other
work.

## Commands

| Command | What it does |
|---|---|
| `clueberry fetch <url>` | Fetch and summarize a public issue or PR. |
| `clueberry inspect <url> [--term NAME ...] [--show-text]` | Fetch, then collect repository evidence and list it. |
| `clueberry analyze <url> [--term NAME ...] [--output FILE]` | The full pipeline: fetch, inspect, extract and assess claims. `--output` also writes a Markdown report. |
| `clueberry info` / `--version` / `--help` | Project info, version, help. |

`<url>` is `https://github.com/<owner>/<repo>/issues/<n>` or
`.../pull/<n>`. An `/issues/<n>` URL that is really a pull request is
detected and treated as one. `--term` adds extra search terms for evidence
collection.

### Reading the results

`analyze` prints:

- an overall result line (e.g. `5 claims assessed: 2 VERIFIED, 1 CONTRADICTED, 2 INCONCLUSIVE`);
- one panel per claim, with the claim, the verbatim quote it came from, the
  model's explanation, and each validated citation with the cited lines;
- any validation notes, such as rejected citations or a verdict that was
  downgraded because no citation survived validation;
- claims the model proposed that were rejected as ungrounded.

The Markdown report (`--output`) contains the same information plus GitHub
permalinks to every cited line range at the inspected commit, evidence
collection statistics, and the limitations below. It is written atomically,
so an interrupted run never leaves a partial report. All text taken from
GitHub, the repository or the model is escaped, so it can't inject links,
images or HTML into the report.

## Configuration

All settings are environment variables. They can also be put in a `.env`
file, which is read from the directory you run Clueberry from (not from the
project or install directory).

| Variable | Default | Purpose |
|---|---|---|
| `CLUEBERRY_GITHUB_TOKEN` | unset | Optional GitHub token for a higher API rate limit. |
| `CLUEBERRY_OLLAMA_MODEL` | `qwen3:4b` | Ollama model used for analysis. |
| `CLUEBERRY_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server. |
| `CLUEBERRY_OLLAMA_TIMEOUT_SECONDS` | `300` | Timeout per model call. |
| `CLUEBERRY_OLLAMA_NUM_CTX` | `16384` | Context window requested from Ollama. |
| `CLUEBERRY_OLLAMA_THINK` | unset | Thinking for claim *assessment* (model default; on for Qwen3). |
| `CLUEBERRY_OLLAMA_EXTRACTION_THINK` | `false` | Thinking for claim *extraction*. |

Unauthenticated GitHub access works for public issues and PRs but is limited
to 60 requests per hour.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success. |
| `2` | Invalid URL or option (including a bad `--output` path). |
| `3` | GitHub error: not found, not public, rate limited, or network failure. |
| `4` | Repository inspection failed (fetch failed or a size limit was exceeded). |
| `5` | Model problem: Ollama unreachable, model not installed, or claim extraction failed. |
| `6` | The report file could not be written. |
| `130` | Interrupted with Ctrl-C. Temporary files are removed and no report is written. |

## How it works and how it stays safe

### Repository inspection

- Only `https://github.com/<owner>/<repo>` is fetched, at `HEAD` (issues),
  the PR's exact head commit, or a PR head ref. Branch names are never
  accepted.
- Nothing is checked out or executed. Files are read directly from git's
  object database inside a temporary directory, which is always deleted,
  including after errors, timeouts and Ctrl-C.
- Symlinks, submodules, binary, generated, dependency-directory, oversized
  and malformed-path files are skipped.
- Git runs with a scrubbed environment (no tokens, credentials or user git
  config), with no hooks, no credential helpers, one allowed transport and
  per-command timeouts.
- Fetch depth, tree size, file count, file size, total bytes read and
  evidence count are bounded. Repository size is only checked *after* the
  fetch completes; the download itself is bounded by the git timeout
  (120 s).
- Files changed by a PR, paths mentioned in the issue/PR, related tests and
  the README are looked at first. Other files are searched for code-like
  terms (identifiers, dotted names, paths) from the title and body.
- History evidence lists recent commits touching a file, within the shallow
  fetch depth. The oldest fetched commit is never reported as changing a
  file, because git can't tell what it changed without its parent.

### Claim analysis

The model only *proposes*; deterministic code decides what is accepted:

- A claim is kept only if its quote appears verbatim in the issue/PR text
  (ignoring whitespace, case, quote marks and markdown backticks).
- Every citation must name an evidence item the model was actually shown,
  with the same path, a line range inside that item (no lines for history
  items), and, if a commit is cited, the inspected commit. The cited lines
  must also share at least one meaningful word or number with the claim,
  which rejects clearly unrelated citations. Invalid citations are
  discarded.
- Any verdict other than `INCONCLUSIVE` left without a valid citation is
  downgraded to `INCONCLUSIVE`. The model's original answer is kept and
  shown.
- Finished results are re-checked independently against the collected
  evidence.
- Issue/PR text and repository content are given to the model inside
  markers built from a random per-request nonce, with instructions to treat
  them strictly as data. Control characters are stripped, inputs are
  truncated, and output is constrained to a JSON schema at temperature 0.
  Proxy environment variables are ignored.
- A timeout or malformed answer for one claim makes only that claim
  `INCONCLUSIVE`.
- The model sits behind a small provider interface, so it can be replaced.

## Tested models

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
thinking-mode assessment exceeded the earlier 180 s limit. Thinking is on
for assessment because it was the only setting that got every benchmark
verdict right; it is off for extraction because thinking made extraction
time out. Models without thinking support work with the defaults
(`CLUEBERRY_OLLAMA_THINK=true` would make Ollama reject them).

## Limitations

- **Verdicts can be wrong.** Validation proves a citation exists in the
  collected evidence and shares a term with the claim, not that it supports
  the claim. A model can still cite a loosely related line or pick the
  wrong verdict. Treat results as a starting point for a maintainer, not a
  ruling.
- **Small benchmark.** Accuracy was measured on five hand-written claims and
  two real issues, not a large evaluation. Thinking-mode assessment was not
  measured end to end on issue #7600, because one claim timed out under the
  previous 180 s limit.
- **Claims about things outside the code** (RFCs, user environments, type
  checker output) usually can't be checked from repository evidence and
  should come back `INCONCLUSIVE`; models don't always do this.
- **Prompt injection:** a sentence planted in an issue can become a grounded
  claim, but it still needs a valid citation to get anything other than
  `INCONCLUSIVE`.
- **Snapshot only:** pull requests are inspected at their head commit, not as
  a base-to-head diff, and "(file overview)" snippets may not include the
  changed lines. Issues are inspected at the default branch's current `HEAD`,
  so results for the same issue can change as the repository changes. Every
  report records the exact commit.
- **Speed:** with the default model, analysis takes minutes, not seconds.
- **GitHub only**, public repositories only, and an Ollama server is required
  for `analyze`.

## Development

```bash
ruff check .
ruff format --check .
pytest
```

The test suite needs no network or model. GitHub and Ollama are mocked at
the HTTP layer, and repository inspection runs against small local git
repositories created by the tests. The end-to-end tests run the real
`clueberry analyze` command through the whole pipeline. CI runs Ruff and
pytest on every pull request.

### Project layout

```
src/clueberry/
  github/         GitHub REST intake (URLs, client, models)
  investigation/  sandboxed git fetch, file filtering, evidence collection
  analysis/       Ollama provider, prompts, claim/citation validation, analyzer
  report.py       Markdown report rendering and atomic writing
  main.py         Typer CLI
tests/            pytest suite (unit, integration and end-to-end)
examples/         real example runs with actual output
```

## Technology

Python 3.12, [Typer](https://typer.tiangolo.com/),
[Rich](https://rich.readthedocs.io/),
[Pydantic](https://docs.pydantic.dev/) and Pydantic Settings,
[httpx](https://www.python-httpx.org/), [Ollama](https://ollama.com/) with
Qwen3-4B, [pytest](https://docs.pytest.org/),
[Ruff](https://docs.astral.sh/ruff/), and GitHub Actions. There is no
database, server or cloud service.

## License

MIT — see [LICENSE](LICENSE).
