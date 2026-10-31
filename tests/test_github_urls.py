import pytest
from clueberry.github.urls import InvalidGitHubURLError, parse_github_issue_or_pr_url


def test_parses_issue_url() -> None:
    ref = parse_github_issue_or_pr_url("https://github.com/octocat/Hello-World/issues/42")
    assert ref.owner == "octocat"
    assert ref.repo == "Hello-World"
    assert ref.number == 42
    assert ref.kind == "issue"


def test_parses_pull_request_url() -> None:
    ref = parse_github_issue_or_pr_url("https://github.com/octocat/Hello-World/pull/7")
    assert ref.kind == "pull_request"
    assert ref.number == 7


def test_tolerates_trailing_slash_and_whitespace() -> None:
    ref = parse_github_issue_or_pr_url("  https://github.com/octocat/Hello-World/issues/1/  ")
    assert ref.number == 1


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "https://gitlab.com/owner/repo/issues/1",
        "https://github.com/owner/repo",
        "https://github.com/owner/repo/issues/not-a-number",
        "https://github.com/owner/repo/commits/abc123",
    ],
)
def test_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(InvalidGitHubURLError):
        parse_github_issue_or_pr_url(url)
