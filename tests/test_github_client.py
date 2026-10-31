from __future__ import annotations

import clueberry.github.client as client_module
import httpx
import pytest
from clueberry.github.client import (
    GitHubAPIError,
    GitHubClient,
    GitHubNetworkError,
    GitHubRateLimitError,
    GitHubResourceNotFoundError,
)
from clueberry.github.urls import GitHubReference

_ISSUE_PAYLOAD = {
    "number": 1,
    "title": "Found a bug",
    "state": "open",
    "body": "Something is broken.",
    "user": {"login": "octocat", "html_url": "https://github.com/octocat"},
    "html_url": "https://github.com/octocat/Hello-World/issues/1",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-02T00:00:00Z",
    "comments": 0,
    "labels": [{"name": "bug"}],
}

_PR_PAYLOAD = {
    "number": 7,
    "title": "Fix bug",
    "state": "open",
    "body": "Fixes it.",
    "user": {"login": "octocat"},
    "html_url": "https://github.com/octocat/Hello-World/pull/7",
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-02T00:00:00Z",
    "comments": 0,
    "labels": [],
    # Real GitHub issue responses for a PR include this field; our fetch()
    # uses its presence (not just the URL) to decide PR-vs-issue.
    "pull_request": {"url": "https://api.github.com/repos/octocat/Hello-World/pulls/7"},
}

_PR_EXTRA_PAYLOAD = {
    "additions": 1,
    "deletions": 1,
    "changed_files": 1,
    "mergeable": True,
    "base": {"ref": "main"},
    "head": {"ref": "fix-1"},
}

_PR_FILES_PAYLOAD = [
    {"filename": "a.py", "status": "modified", "additions": 1, "deletions": 1, "changes": 2}
]


def _issue_ref(number: int = 1) -> GitHubReference:
    return GitHubReference(owner="octocat", repo="Hello-World", number=number, kind="issue")


def _pr_ref(number: int = 7) -> GitHubReference:
    return GitHubReference(owner="octocat", repo="Hello-World", number=number, kind="pull_request")


def test_fetch_issue_with_comments() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 1,
                        "user": {"login": "someone"},
                        "body": "me too",
                        "created_at": "2024-01-03T00:00:00Z",
                    }
                ],
            )
        return httpx.Response(200, json=_ISSUE_PAYLOAD)

    client = GitHubClient(transport=httpx.MockTransport(handler))
    result = client.fetch(_issue_ref())

    assert result.kind == "issue"
    assert result.issue.title == "Found a bug"
    assert result.issue.labels == ["bug"]
    assert len(result.comments) == 1
    assert result.pull_request is None
    assert result.changed_files is None


def test_fetch_pull_request_includes_extra_and_files() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/comments"):
            return httpx.Response(200, json=[])
        if path.endswith("/files"):
            return httpx.Response(200, json=_PR_FILES_PAYLOAD)
        if "/pulls/" in path:
            return httpx.Response(200, json=_PR_EXTRA_PAYLOAD)
        return httpx.Response(200, json=_PR_PAYLOAD)

    client = GitHubClient(transport=httpx.MockTransport(handler))
    result = client.fetch(_pr_ref())

    assert result.kind == "pull_request"
    assert result.pull_request is not None
    assert result.pull_request.additions == 1
    assert result.pull_request.base_ref == "main"
    assert result.changed_files is not None
    assert result.changed_files[0].filename == "a.py"


def test_issue_url_detects_and_resolves_underlying_pull_request() -> None:
    """An /issues/N URL for a number that is actually a PR should be upgraded."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/comments"):
            return httpx.Response(200, json=[])
        if path.endswith("/files"):
            return httpx.Response(200, json=_PR_FILES_PAYLOAD)
        if "/pulls/" in path:
            return httpx.Response(200, json=_PR_EXTRA_PAYLOAD)
        return httpx.Response(200, json=_PR_PAYLOAD)

    client = GitHubClient(transport=httpx.MockTransport(handler))
    result = client.fetch(_issue_ref(number=7))  # note: kind="issue" in the ref itself

    assert result.kind == "pull_request"
    assert result.pull_request is not None
    assert result.changed_files is not None
    assert result.changed_files[0].filename == "a.py"


def test_issue_and_pull_urls_identify_the_same_pr() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/comments"):
            return httpx.Response(200, json=[])
        if path.endswith("/files"):
            return httpx.Response(200, json=_PR_FILES_PAYLOAD)
        if "/pulls/" in path:
            return httpx.Response(200, json=_PR_EXTRA_PAYLOAD)
        return httpx.Response(200, json=_PR_PAYLOAD)

    via_issue = GitHubClient(transport=httpx.MockTransport(handler)).fetch(_issue_ref(number=7))
    via_pull = GitHubClient(transport=httpx.MockTransport(handler)).fetch(_pr_ref(number=7))

    assert via_issue.kind == via_pull.kind == "pull_request"
    assert via_issue.pull_request == via_pull.pull_request
    assert via_issue.changed_files == via_pull.changed_files


def test_plain_issue_is_not_misclassified_as_pull_request() -> None:
    """A normal issue URL/number (no `pull_request` field) stays an issue."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=_ISSUE_PAYLOAD)

    client = GitHubClient(transport=httpx.MockTransport(handler))
    result = client.fetch(_issue_ref())

    assert result.kind == "issue"
    assert result.pull_request is None
    assert result.changed_files is None


def test_not_found_raises_resource_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = GitHubClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubResourceNotFoundError):
        client.fetch(_issue_ref())


def test_rate_limit_raises_with_reset_time() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1700000000"},
            json={"message": "rate limited"},
        )

    client = GitHubClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubRateLimitError) as exc_info:
        client.fetch(_issue_ref())
    assert exc_info.value.reset_at == 1700000000


def test_secondary_rate_limit_uses_retry_after() -> None:
    """A 429 with Retry-After but no exhausted X-RateLimit-Remaining is still a rate limit."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "30"},
            json={"message": "secondary rate limit"},
        )

    client = GitHubClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubRateLimitError) as exc_info:
        client.fetch(_issue_ref())
    assert exc_info.value.retry_after == 30
    assert exc_info.value.reset_at is None


def test_forbidden_without_rate_limit_headers_is_not_a_rate_limit() -> None:
    """A plain 403 (e.g. access forbidden) must not be misreported as rate limiting."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "Forbidden"})

    client = GitHubClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubAPIError) as exc_info:
        client.fetch(_issue_ref())
    assert not isinstance(exc_info.value, GitHubRateLimitError)


def test_comments_pagination_fetches_all_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(client_module, "_PER_PAGE", 2)

    pages = {
        1: [
            {"id": 1, "user": {"login": "a"}, "body": "x", "created_at": "2024-01-01T00:00:00Z"},
            {"id": 2, "user": {"login": "b"}, "body": "y", "created_at": "2024-01-01T00:00:00Z"},
        ],
        2: [
            {"id": 3, "user": {"login": "c"}, "body": "z", "created_at": "2024-01-01T00:00:00Z"},
        ],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/comments"):
            page = int(request.url.params.get("page", "1"))
            return httpx.Response(200, json=pages.get(page, []))
        return httpx.Response(200, json=_ISSUE_PAYLOAD)

    client = GitHubClient(transport=httpx.MockTransport(handler))
    result = client.fetch(_issue_ref())

    assert [c.id for c in result.comments] == [1, 2, 3]


def test_network_error_is_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    client = GitHubClient(transport=httpx.MockTransport(handler))
    with pytest.raises(GitHubNetworkError):
        client.fetch(_issue_ref())


def test_authenticated_client_sends_bearer_token() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization", "")
        if request.url.path.endswith("/comments"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=_ISSUE_PAYLOAD)

    client = GitHubClient(token="secret-token", transport=httpx.MockTransport(handler))
    client.fetch(_issue_ref())

    assert captured["authorization"] == "Bearer secret-token"


def test_requests_only_target_official_github_api_host() -> None:
    """Every request a fetch() makes -- for both issue and PR data -- stays on api.github.com."""
    seen: set[tuple[str, str | None]] = set()

    def handler(request: httpx.Request) -> httpx.Response:
        seen.add((request.url.scheme, request.url.host))
        path = request.url.path
        if path.endswith("/comments"):
            return httpx.Response(200, json=[])
        if path.endswith("/files"):
            return httpx.Response(200, json=_PR_FILES_PAYLOAD)
        if "/pulls/" in path:
            return httpx.Response(200, json=_PR_EXTRA_PAYLOAD)
        return httpx.Response(200, json=_PR_PAYLOAD)

    client = GitHubClient(token="secret-token", transport=httpx.MockTransport(handler))
    client.fetch(_pr_ref())

    assert seen == {("https", "api.github.com")}


def test_error_never_leaks_token_or_authorization_header() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    client = GitHubClient(token="super-secret-token", transport=httpx.MockTransport(handler))

    with pytest.raises(GitHubAPIError) as exc_info:
        client.fetch(_issue_ref())

    message = str(exc_info.value)
    assert "super-secret-token" not in message
    assert "Authorization" not in message
    assert "Bearer" not in message
