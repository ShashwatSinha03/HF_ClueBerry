from __future__ import annotations

import httpx

from .models import ChangedFile, GitHubFetchResult, IssueComment, IssueDetails, PullRequestExtra
from .urls import GitHubReference

GITHUB_API_BASE = "https://api.github.com"
USER_AGENT = "clueberry-hackday-project"


class GitHubAPIError(RuntimeError):
    """A GitHub API request failed in a way not covered by a more specific error."""


class GitHubResourceNotFoundError(GitHubAPIError):
    """The requested issue or pull request does not exist, or isn't public."""


class GitHubRateLimitError(GitHubAPIError):
    """The GitHub API rate limit has been exhausted."""

    def __init__(self, message: str, reset_at: int | None = None) -> None:
        super().__init__(message)
        self.reset_at = reset_at


class GitHubNetworkError(GitHubAPIError):
    """A network-level failure occurred while talking to the GitHub API."""


class GitHubClient:
    """A small, direct wrapper around the public GitHub REST API.

    Supports unauthenticated access (subject to GitHub's lower rate limit)
    and an optional bearer token for a higher rate limit.
    """

    def __init__(
        self,
        token: str | None = None,
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._client = httpx.Client(
            base_url=GITHUB_API_BASE, headers=headers, timeout=timeout, transport=transport
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _get(self, path: str) -> httpx.Response:
        try:
            response = self._client.get(path)
        except httpx.RequestError as exc:
            raise GitHubNetworkError(f"Network error calling GitHub API: {exc}") from exc

        if response.status_code == 404:
            raise GitHubResourceNotFoundError(f"GitHub resource not found: {path}")

        if response.status_code == 403 and response.headers.get("X-RateLimit-Remaining") == "0":
            reset = response.headers.get("X-RateLimit-Reset")
            raise GitHubRateLimitError(
                "GitHub API rate limit exceeded. Set CLUEBERRY_GITHUB_TOKEN for a higher limit.",
                reset_at=int(reset) if reset else None,
            )

        if response.status_code >= 400:
            raise GitHubAPIError(
                f"GitHub API request to {path} failed with status {response.status_code}: "
                f"{response.text[:200]}"
            )

        return response

    def fetch(self, ref: GitHubReference) -> GitHubFetchResult:
        """Fetch metadata, body, and comments for an issue or PR (plus PR-only details)."""
        issue_data = self._get(f"/repos/{ref.owner}/{ref.repo}/issues/{ref.number}").json()
        issue = IssueDetails.from_api(issue_data)

        comments_data = self._get(
            f"/repos/{ref.owner}/{ref.repo}/issues/{ref.number}/comments"
        ).json()
        comments = [IssueComment.model_validate(c) for c in comments_data]

        pull_request: PullRequestExtra | None = None
        changed_files: list[ChangedFile] | None = None
        if ref.kind == "pull_request":
            pr_data = self._get(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}").json()
            pull_request = PullRequestExtra.from_api(pr_data)

            files_data = self._get(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/files").json()
            changed_files = [ChangedFile.model_validate(f) for f in files_data]

        return GitHubFetchResult(
            kind=ref.kind,
            owner=ref.owner,
            repo=ref.repo,
            issue=issue,
            pull_request=pull_request,
            comments=comments,
            changed_files=changed_files,
        )
