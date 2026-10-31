from __future__ import annotations

import httpx

from .models import ChangedFile, GitHubFetchResult, IssueComment, IssueDetails, PullRequestExtra
from .urls import GitHubReference

GITHUB_API_BASE = "https://api.github.com"
USER_AGENT = "clueberry-hackday-project"

#: Safety cap on pages fetched per paginated collection (comments, changed
#: files). 100 items/page * 20 pages = 2000 items, comfortably beyond what a
#: hackathon-scope tool needs to handle, while guaranteeing the loop ends.
_MAX_PAGES = 20
_PER_PAGE = 100


class GitHubAPIError(RuntimeError):
    """A GitHub API request failed in a way not covered by a more specific error."""


class GitHubResourceNotFoundError(GitHubAPIError):
    """The requested issue or pull request does not exist, or isn't public."""


class GitHubRateLimitError(GitHubAPIError):
    """GitHub's primary or secondary rate limit has been hit."""

    def __init__(
        self,
        message: str,
        reset_at: int | None = None,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.reset_at = reset_at
        self.retry_after = retry_after


class GitHubNetworkError(GitHubAPIError):
    """A network-level failure occurred while talking to the GitHub API."""


class GitHubClient:
    """A small, direct wrapper around the public GitHub REST API.

    Supports unauthenticated access (subject to GitHub's lower rate limit)
    and an optional bearer token for a higher rate limit. Every request is
    issued against a fixed `base_url` (api.github.com) with a relative path
    built only from regex-validated owner/repo/number values, and redirects
    are never followed -- so a bearer token can never be sent to any host
    other than the official GitHub API.
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
            base_url=GITHUB_API_BASE,
            headers=headers,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
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

        if response.status_code in (403, 429):
            self._raise_if_rate_limited(response)
            # A 403/429 without rate-limit headers is a genuine error (e.g.
            # access forbidden), not a rate limit -- fall through below.

        if not (200 <= response.status_code < 300):
            raise GitHubAPIError(
                f"GitHub API request to {path} failed with status {response.status_code}: "
                f"{response.text[:200]}"
            )

        return response

    @staticmethod
    def _raise_if_rate_limited(response: httpx.Response) -> None:
        """Raise GitHubRateLimitError for a 403/429 that is actually a rate limit.

        GitHub signals its *primary* rate limit via `X-RateLimit-Remaining: 0`
        (with `X-RateLimit-Reset` as the epoch-seconds reset time), and its
        *secondary* (abuse-detection) rate limit via a `Retry-After` header,
        which may appear without `X-RateLimit-Remaining` hitting zero. A
        403/429 with neither header is not a rate limit at all.
        """
        remaining = response.headers.get("X-RateLimit-Remaining")
        reset = response.headers.get("X-RateLimit-Reset")
        retry_after = response.headers.get("Retry-After")

        if remaining == "0":
            message = "GitHub API primary rate limit exceeded."
            if reset:
                message += f" Resets at epoch {reset}."
            message += " Set CLUEBERRY_GITHUB_TOKEN for a higher limit."
            raise GitHubRateLimitError(
                message,
                reset_at=int(reset) if reset else None,
                retry_after=int(retry_after) if retry_after else None,
            )

        if retry_after is not None:
            raise GitHubRateLimitError(
                f"GitHub API secondary rate limit triggered; retry after {retry_after}s.",
                retry_after=int(retry_after),
            )

    def _get_all_pages(self, path: str) -> list[dict]:
        """GET every page of a paginated list endpoint.

        Uses the simple "short page means last page" heuristic (stop once a
        page returns fewer than `_PER_PAGE` items) rather than parsing the
        `Link` header, which is sufficient for this tool's scope. Capped at
        `_MAX_PAGES` pages as a safety bound.
        """
        items: list[dict] = []
        separator = "&" if "?" in path else "?"
        for page in range(1, _MAX_PAGES + 1):
            response = self._get(f"{path}{separator}per_page={_PER_PAGE}&page={page}")
            page_items = response.json()
            if not isinstance(page_items, list):
                raise GitHubAPIError(f"Expected a list response from {path}, got {page_items!r}")
            items.extend(page_items)
            if len(page_items) < _PER_PAGE:
                break
        return items

    def fetch(self, ref: GitHubReference) -> GitHubFetchResult:
        """Fetch metadata, body, and comments for an issue or PR (plus PR-only details).

        An `/issues/{n}` URL and a `/pull/{n}` URL for the same underlying
        pull request resolve to the same result: GitHub's issues API returns
        a `pull_request` field for issues that are actually PRs, and that
        field -- not just which URL form was used -- decides whether PR
        extras and changed files are fetched.
        """
        issue_data = self._get(f"/repos/{ref.owner}/{ref.repo}/issues/{ref.number}").json()
        issue = IssueDetails.from_api(issue_data)
        is_pull_request = ref.kind == "pull_request" or bool(issue_data.get("pull_request"))

        comments_data = self._get_all_pages(
            f"/repos/{ref.owner}/{ref.repo}/issues/{ref.number}/comments"
        )
        comments = [IssueComment.model_validate(c) for c in comments_data]

        pull_request: PullRequestExtra | None = None
        changed_files: list[ChangedFile] | None = None
        if is_pull_request:
            pr_data = self._get(f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}").json()
            pull_request = PullRequestExtra.from_api(pr_data)

            files_data = self._get_all_pages(
                f"/repos/{ref.owner}/{ref.repo}/pulls/{ref.number}/files"
            )
            changed_files = [ChangedFile.model_validate(f) for f in files_data]

        return GitHubFetchResult(
            kind="pull_request" if is_pull_request else "issue",
            owner=ref.owner,
            repo=ref.repo,
            issue=issue,
            pull_request=pull_request,
            comments=comments,
            changed_files=changed_files,
        )
