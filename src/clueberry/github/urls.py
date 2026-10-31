from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

GitHubResourceKind = Literal["issue", "pull_request"]

_URL_PATTERN = re.compile(
    r"^https?://github\.com/"
    r"(?P<owner>[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)/"
    r"(?P<repo>[A-Za-z0-9_.-]+)/"
    r"(?P<kind>issues|pull)/"
    r"(?P<number>\d+)/?$"
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

    Accepts URLs of the form:
      https://github.com/{owner}/{repo}/issues/{number}
      https://github.com/{owner}/{repo}/pull/{number}

    Raises InvalidGitHubURLError for anything else.
    """
    match = _URL_PATTERN.match(url.strip())
    if not match:
        raise InvalidGitHubURLError(f"Not a recognizable GitHub issue or pull request URL: {url!r}")

    kind: GitHubResourceKind = "pull_request" if match["kind"] == "pull" else "issue"
    return GitHubReference(
        owner=match["owner"],
        repo=match["repo"],
        number=int(match["number"]),
        kind=kind,
    )
