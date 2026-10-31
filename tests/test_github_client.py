from __future__ import annotations

import httpx
import pytest
from clueberry.github.client import (
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
