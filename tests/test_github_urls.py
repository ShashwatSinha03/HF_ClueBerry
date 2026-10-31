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


def test_accepts_uppercase_host() -> None:
    ref = parse_github_issue_or_pr_url("https://GitHub.com/octocat/Hello-World/issues/1")
    assert ref.owner == "octocat"


@pytest.mark.parametrize(
    "url",
    [
        "not a url",
        "https://gitlab.com/owner/repo/issues/1",
        "https://github.com/owner/repo",
        "https://github.com/owner/repo/issues/not-a-number",
        "https://github.com/owner/repo/commits/abc123",
        "ftp://github.com/owner/repo/issues/1",
    ],
)
def test_rejects_invalid_urls(url: str) -> None:
    with pytest.raises(InvalidGitHubURLError):
        parse_github_issue_or_pr_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com.evil.com/owner/repo/issues/1",
        "https://notgithub.com/owner/repo/issues/1",
        "https://github.com@evil.com/owner/repo/issues/1",
        "https://evil.com/github.com/owner/repo/issues/1",
        "https://api.github.com/owner/repo/issues/1",
        "https://gist.github.com/owner/repo/issues/1",
        "https://github.com:8443/owner/repo/issues/1",
        "https://user:pass@github.com/owner/repo/issues/1",
    ],
)
def test_rejects_lookalike_or_unexpected_hosts(url: str) -> None:
    with pytest.raises(InvalidGitHubURLError):
        parse_github_issue_or_pr_url(url)
