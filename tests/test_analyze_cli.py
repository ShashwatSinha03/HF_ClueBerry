from __future__ import annotations

import json
from typing import Any

import clueberry.main as main_module
import pytest
from clueberry.analysis import ModelUnavailableError
from clueberry.github.models import GitHubFetchResult, IssueDetails
from test_analysis import BODY, SHA, TITLE, _inspection
from typer.testing import CliRunner

URL = "https://github.com/psf/requests/issues/7611"


class _ScriptedProvider:
    name = "ollama/fake"
    available = True

    instances: list[_ScriptedProvider] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.think = kwargs.get("think")
        self.calls: list[str] = []
        _ScriptedProvider.instances.append(self)

    def __enter__(self) -> _ScriptedProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def ensure_available(self) -> None:
        if not self.available:
            raise ModelUnavailableError("Model 'qwen3:4b' is not installed in Ollama.")

    def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        if "claims" in schema["properties"]:
            self.calls.append("extraction")
            return json.dumps(
                {
                    "claims": [
                        {
                            "text": "Status code 102 is mapped to [red]early-hints",
                            "quote": "status code 102 is mapped to early-hints",
                        }
                    ]
                }
            )
        self.calls.append("assessment")
        return json.dumps(
            {
                "verdict": "VERIFIED",
                "explanation": "Line 27 maps 102 to early-hints.",
                "citations": [
                    {"evidence_id": "E1", "path": "src/requests/status_codes.py", "start_line": 27}
                ],
            }
        )


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> type[_ScriptedProvider]:
    fetched = GitHubFetchResult(
        kind="issue",
        owner="psf",
        repo="requests",
        issue=IssueDetails(
            number=7611,
            title=TITLE,
            state="open",
            body=BODY,
            html_url=URL,
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        ),
    )
    monkeypatch.setattr(main_module, "_fetch_or_exit", lambda url: fetched)
    monkeypatch.setattr(main_module, "inspect_repository", lambda *a, **k: _inspection())
    monkeypatch.setattr(main_module, "OllamaProvider", _ScriptedProvider)
    monkeypatch.setattr(_ScriptedProvider, "instances", [])
    return _ScriptedProvider


def test_analyze_prints_verdicts_and_validated_evidence(fakes: type[_ScriptedProvider]) -> None:
    result = CliRunner().invoke(main_module.app, ["analyze", URL])

    assert result.exit_code == 0, result.stdout
    assert SHA in result.stdout
    assert "Result: 1 claim assessed: 1 VERIFIED." in result.stdout
    assert " C1 VERIFIED" in result.stdout
    assert "Status code 102 is mapped to [red]early-hints" in result.stdout  # markup not applied
    assert "E1 source src/requests/status_codes.py:27" in result.stdout
    assert '27 │     102: ("processing", "early-hints"),' in result.stdout  # cited line shown


def test_analyze_uses_thinking_off_for_extraction_by_default(
    fakes: type[_ScriptedProvider], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CLUEBERRY_OLLAMA_THINK", raising=False)
    monkeypatch.delenv("CLUEBERRY_OLLAMA_EXTRACTION_THINK", raising=False)
    CliRunner().invoke(main_module.app, ["analyze", URL])

    by_think = {p.think: p.calls for p in fakes.instances}
    assert by_think == {None: ["assessment"], False: ["extraction"]}


def test_analyze_fails_fast_when_model_is_missing(
    fakes: type[_ScriptedProvider], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(fakes, "available", False)
    result = CliRunner().invoke(main_module.app, ["analyze", URL])

    assert result.exit_code == main_module.EXIT_MODEL
    assert "Model unavailable" in result.stdout
    assert "not installed" in result.stdout
