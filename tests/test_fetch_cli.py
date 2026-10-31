from __future__ import annotations

import clueberry.main as main_module
import pytest
from clueberry.github.models import GitHubFetchResult, IssueDetails
from typer.testing import CliRunner

runner = CliRunner()


class _FakeClient:
    """Stands in for GitHubClient so the CLI test doesn't hit the network."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def fetch(self, ref: object) -> GitHubFetchResult:
        issue = IssueDetails(
            number=1,
            title="Example issue",
            state="open",
            body="Body text",
            user=None,
            html_url="https://github.com/octocat/Hello-World/issues/1",
            created_at="2024-01-01T00:00:00Z",
            updated_at="2024-01-02T00:00:00Z",
            comments=0,
            labels=["bug"],
        )
        return GitHubFetchResult(
            kind="issue",
            owner="octocat",
            repo="Hello-World",
            issue=issue,
            pull_request=None,
            comments=[],
            changed_files=None,
        )


@pytest.fixture(autouse=True)
def _fake_github_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "GitHubClient", _FakeClient)


def test_fetch_command_prints_summary() -> None:
    result = runner.invoke(
        main_module.app, ["fetch", "https://github.com/octocat/Hello-World/issues/1"]
    )
    assert result.exit_code == 0
    assert "Example issue" in result.stdout
    assert "octocat/Hello-World" in result.stdout


def test_fetch_command_rejects_invalid_url() -> None:
    result = runner.invoke(main_module.app, ["fetch", "not-a-github-url"])
    assert result.exit_code != 0
    assert "Invalid URL" in result.stdout
