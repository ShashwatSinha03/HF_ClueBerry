from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

GitHubResourceKind = Literal["issue", "pull_request"]

_ALLOWED_SCHEMES = {"http", "https"}
_ALLOWED_HOST = "github.com"
_ALLOWED_PORTS = (None, 80, 443)

_PATH_PATTERN = re.compile(
    r"^/(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)"
    r"/(?P<repo>[A-Za-z0-9_.-]+)"
    r"/(?P<kind>issues|pull)"
    r"/(?P<number>\d+)/?$"
)


class InvalidGitHubURLError(ValueError):
    """Raised when a string is not a recognizable public GitHub issue/PR URL."""


@dataclass(frozen=True)
class GitHubReference:
    """A parsed reference to a single public GitHub issue or pull request."""

    owner: str
    repo: str
    number: int
    kind: GitHubResourceKind


def parse_github_issue_or_pr_url(url: str) -> GitHubReference:
    """Parse and validate a GitHub issue or pull request URL.

    Accepts only:
      https://github.com/{owner}/{repo}/issues/{number}
      https://github.com/{owner}/{repo}/pull/{number}
    (http is also accepted; GitHub itself redirects it to https.)

    The host, scheme, port, and userinfo are checked explicitly via
    `urlsplit` (not just a single regex over the whole string) so that
    lookalike or unexpected hosts -- subdomains, suffix tricks like
    "github.com.evil.com", or userinfo tricks like "github.com@evil.com" --
    are rejected rather than accidentally matched.

    Raises InvalidGitHubURLError for anything else.
    """
    candidate = url.strip()
    parts = urlsplit(candidate)

    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise InvalidGitHubURLError(f"Unsupported URL scheme: {url!r}")

    if parts.username or parts.password:
        raise InvalidGitHubURLError(f"URL must not contain userinfo: {url!r}")

    if (parts.hostname or "").lower() != _ALLOWED_HOST:
        raise InvalidGitHubURLError(f"Not a github.com URL (host was {parts.hostname!r}): {url!r}")

    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidGitHubURLError(f"Invalid port in URL: {url!r}") from exc
    if port not in _ALLOWED_PORTS:
        raise InvalidGitHubURLError(f"Unexpected port in URL: {url!r}")

    match = _PATH_PATTERN.match(parts.path)
    if not match:
        raise InvalidGitHubURLError(f"Not a recognizable GitHub issue or pull request URL: {url!r}")

    kind: GitHubResourceKind = "pull_request" if match["kind"] == "pull" else "issue"
    return GitHubReference(
        owner=match["owner"],
        repo=match["repo"],
        number=int(match["number"]),
        kind=kind,
    )
