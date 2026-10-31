"""End-to-end tests for `clueberry analyze`.

Everything real runs: the CLI, the GitHub client, the git-based repository
inspection, the analyzer, the Ollama HTTP client and the report writer. Only
the network is replaced: GitHub and Ollama are mocked at the HTTP layer, and
the repository is a local fixture repo instead of a github.com clone.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import clueberry.investigation.git as git_module
import clueberry.main as main_module
import httpx
import pytest
from clueberry.analysis import OllamaProvider
from clueberry.github import GitHubClient
from clueberry.investigation import inspect_repository
from conftest import FixtureRepo
from typer.testing import CliRunner

URL = "https://github.com/acme/calc/issues/1"
CALC = '"""Calculator helpers."""\n\n\ndef add_numbers(a, b):\n    return a + b\n'
ISSUE = {
    "number": 1,
    "title": "add_numbers in src/calc.py returns the sum",
    "state": "open",
    "body": "The function `add_numbers` in src/calc.py returns the sum of its two arguments.",
    "user": {"login": "reporter"},
    "html_url": URL,
    "created_at": "2026-01-01T00:00:00Z",
    "updated_at": "2026-01-01T00:00:00Z",
    "comments": 0,
    "labels": [],
}
CLAIM = {
    "text": "add_numbers returns the sum of its two arguments",
    "quote": "returns the sum of its two arguments",
}


def _chat(answer: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200, json={"message": {"role": "assistant", "content": json.dumps(answer)}}
    )


def _cite_calc(prompt: str) -> dict[str, Any]:
    """A well-behaved model: cite the add_numbers lines of the src/calc.py evidence it was shown."""
    match = re.search(r"\[(E\d+)\] category=source path=src/calc.py lines=\d+-\d+", prompt)
    assert match, prompt
    return {
        "verdict": "VERIFIED",
        "explanation": "add_numbers returns a + b.",
        "citations": [
            {"evidence_id": match[1], "path": "src/calc.py", "start_line": 4, "end_line": 5}
        ],
    }


class Harness:
    def __init__(self, tmp_path: Path, repo: FixtureRepo, monkeypatch: pytest.MonkeyPatch) -> None:
        self.repo = repo
        self.head = repo.commit("initial")
        self.workspaces = tmp_path / "workspaces"
        self.workspaces.mkdir()
        self.reports = tmp_path / "reports"
        self.reports.mkdir()
        self.github_calls: list[str] = []
        self.ollama_calls: list[str] = []
        self.clone_urls: list[str] = []
        self.issue_status = 200
        self.ollama_down = False
        self.assess: Callable[[str], dict[str, Any] | BaseException] = _cite_calc

        monkeypatch.setenv("CLUEBERRY_OLLAMA_MODEL", "qwen3:4b")
        for name in ("CLUEBERRY_OLLAMA_THINK", "CLUEBERRY_OLLAMA_EXTRACTION_THINK"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setattr(
            main_module,
            "GitHubClient",
            lambda token=None: GitHubClient(
                token=token, transport=httpx.MockTransport(self._github)
            ),
        )
        monkeypatch.setattr(
            main_module,
            "OllamaProvider",
            lambda model, **kw: OllamaProvider(
                model, transport=httpx.MockTransport(self._ollama), **kw
            ),
        )
        monkeypatch.setattr(main_module, "inspect_repository", self._inspect)

    def _github(self, request: httpx.Request) -> httpx.Response:
        self.github_calls.append(request.url.path)
        if request.url.path.endswith("/comments"):
            return httpx.Response(200, json=[])
        if request.url.path == "/repos/acme/calc/issues/1" and self.issue_status == 200:
            return httpx.Response(200, json=ISSUE)
        return httpx.Response(404, json={"message": "Not Found"})

    def _ollama(self, request: httpx.Request) -> httpx.Response:
        self.ollama_calls.append(request.url.path)
        if self.ollama_down:
            raise httpx.ConnectError("connection refused")
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:4b", "model": "qwen3:4b"}]})
        payload = json.loads(request.content)
        if "claims" in payload["format"]["properties"]:
            return _chat({"claims": [CLAIM]})
        answer = self.assess(payload["messages"][1]["content"])
        if isinstance(answer, BaseException):
            raise answer
        return _chat(answer)

    def _inspect(self, clone_url: str, repository: str, **kwargs: Any):
        self.clone_urls.append(clone_url)
        return inspect_repository(
            self.repo.url,
            repository,
            allow_local=True,
            workspace_root=self.workspaces,
            **kwargs,
        )

    def run(self, *args: str) -> Any:
        return CliRunner().invoke(main_module.app, ["analyze", *args])


@pytest.fixture
def harness(
    tmp_path: Path, make_repo: Callable[..., FixtureRepo], monkeypatch: pytest.MonkeyPatch
) -> Harness:
    repo = make_repo()
    repo.write("src/calc.py", CALC)
    repo.write("README.md", "# calc\n\nA tiny calculator.\n")
    return Harness(tmp_path, repo, monkeypatch)


def test_full_pipeline_prints_verdict_and_writes_report(harness: Harness) -> None:
    report = harness.reports / "report.md"
    result = harness.run(URL, "--output", str(report))

    assert result.exit_code == main_module.EXIT_OK, result.stdout
    assert harness.clone_urls == ["https://github.com/acme/calc.git"]
    assert "Result: 1 claim assessed: 1 VERIFIED." in result.stdout
    assert "src/calc.py:4-5" in result.stdout
    assert "Report written to" in result.stdout

    text = report.read_text()
    assert text.startswith("# Clueberry report: add\\_numbers in src/calc.py returns the sum")
    assert f"| Commit inspected | `{harness.head}` |" in text
    assert "| Model | ollama/qwen3:4b |" in text
    assert f"https://github.com/acme/calc/blob/{harness.head}/src/calc.py#L4-L5" in text
    assert "    4 | def add_numbers(a, b):\n    5 |     return a + b" in text
    assert list(harness.workspaces.iterdir()) == []
    assert [p.name for p in harness.reports.iterdir()] == ["report.md"]


def test_fabricated_citation_is_downgraded_end_to_end(harness: Harness) -> None:
    harness.assess = lambda prompt: {
        "verdict": "VERIFIED",
        "explanation": "Trust me.",
        "citations": [{"evidence_id": "E99", "path": "src/calc.py", "start_line": 4}],
    }
    report = harness.reports / "report.md"
    result = harness.run(URL, "-o", str(report))

    assert result.exit_code == main_module.EXIT_OK, result.stdout
    assert "1 INCONCLUSIVE" in result.stdout
    assert "Model answered VERIFIED; validation changed it to INCONCLUSIVE." in result.stdout
    text = report.read_text()
    assert "### C1: INCONCLUSIVE" in text
    assert "Rejected citation: 'E99' is not an evidence item that was provided" in text


def test_works_without_writing_a_report(harness: Harness) -> None:
    result = harness.run(URL)
    assert result.exit_code == main_module.EXIT_OK
    assert "Report written" not in result.stdout
    assert list(harness.reports.iterdir()) == []


def test_unavailable_model_fails_before_any_github_or_git_work(harness: Harness) -> None:
    harness.ollama_down = True
    result = harness.run(URL, "-o", str(harness.reports / "report.md"))

    assert result.exit_code == main_module.EXIT_MODEL
    assert "Model unavailable" in result.stdout and "ollama serve" in result.stdout
    assert harness.github_calls == [] and harness.clone_urls == []
    assert list(harness.reports.iterdir()) == []


def test_missing_issue_exits_with_github_code(harness: Harness) -> None:
    harness.issue_status = 404
    result = harness.run(URL, "-o", str(harness.reports / "report.md"))

    assert result.exit_code == main_module.EXIT_GITHUB
    assert "Not found" in result.stdout
    assert harness.clone_urls == []
    assert list(harness.reports.iterdir()) == []


def test_invalid_url_is_a_usage_error(harness: Harness) -> None:
    result = harness.run("https://gitlab.com/acme/calc/issues/1")
    assert result.exit_code == main_module.EXIT_USAGE
    assert "Invalid URL" in result.stdout


def test_bad_output_path_fails_before_any_work(harness: Harness, tmp_path: Path) -> None:
    for bad in (tmp_path / "missing-dir" / "report.md", harness.reports):
        result = harness.run(URL, "-o", str(bad))
        assert result.exit_code == main_module.EXIT_USAGE
        assert "Invalid --output" in result.stdout
    assert harness.ollama_calls == [] and harness.github_calls == []


def test_inspection_failure_exits_with_inspection_code(
    harness: Harness, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(harness.repo, "path", tmp_path / "no-such-repo")
    result = harness.run(URL, "-o", str(harness.reports / "report.md"))

    assert result.exit_code == main_module.EXIT_INSPECTION
    assert "Repository inspection failed" in result.stdout
    assert list(harness.workspaces.iterdir()) == []
    assert list(harness.reports.iterdir()) == []


def test_report_write_failure_exits_with_report_code(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_write(path: Path, content: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(main_module, "write_report", broken_write)
    result = harness.run(URL, "-o", str(harness.reports / "report.md"))

    assert result.exit_code == main_module.EXIT_REPORT
    assert "Could not write report" in result.stdout and "disk full" in result.stdout


def test_interrupt_during_analysis_cleans_up_and_writes_nothing(harness: Harness) -> None:
    harness.assess = lambda prompt: KeyboardInterrupt()
    result = harness.run(URL, "-o", str(harness.reports / "report.md"))

    assert result.exit_code == main_module.EXIT_INTERRUPTED
    assert "Interrupted." in result.stdout and "no report was written" in result.stdout
    assert list(harness.workspaces.iterdir()) == []
    assert list(harness.reports.iterdir()) == []


def test_interrupt_during_git_fetch_removes_the_workspace(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_run = subprocess.run

    def interrupted_fetch(cmd: list[str], **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        if "fetch" in cmd:
            raise KeyboardInterrupt
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(git_module.subprocess, "run", interrupted_fetch)
    result = harness.run(URL, "-o", str(harness.reports / "report.md"))

    assert result.exit_code == main_module.EXIT_INTERRUPTED
    assert list(harness.workspaces.iterdir()) == []
    assert list(harness.reports.iterdir()) == []
