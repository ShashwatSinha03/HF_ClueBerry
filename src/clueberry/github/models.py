from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .urls import GitHubResourceKind


class GitHubUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    login: str
    html_url: str | None = None


class IssueComment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    user: GitHubUser | None = None
    body: str | None = None
    created_at: datetime
    html_url: str | None = None


class IssueDetails(BaseModel):
    """Metadata and body for an issue, or for a PR's issue-shaped counterpart."""

    model_config = ConfigDict(extra="ignore")

    number: int
    title: str
    state: str
    body: str | None = None
    user: GitHubUser | None = None
    html_url: str
    created_at: datetime
    updated_at: datetime
    comments: int = 0
    labels: list[str] = []

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> IssueDetails:
        labels = [
            label["name"] if isinstance(label, dict) else str(label)
            for label in data.get("labels", [])
        ]
        return cls.model_validate({**data, "labels": labels})


class PullRequestExtra(BaseModel):
    """Fields only available from the pulls API, beyond the shared issue fields."""

    model_config = ConfigDict(extra="ignore")

    additions: int = 0
    deletions: int = 0
    changed_files: int = 0
    mergeable: bool | None = None
    base_ref: str
    head_ref: str

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> PullRequestExtra:
        return cls.model_validate(
            {
                "additions": data.get("additions", 0),
                "deletions": data.get("deletions", 0),
                "changed_files": data.get("changed_files", 0),
                "mergeable": data.get("mergeable"),
                "base_ref": data["base"]["ref"],
                "head_ref": data["head"]["ref"],
            }
        )


class ChangedFile(BaseModel):
    """Metadata about one file changed by a pull request.

    Deliberately excludes the GitHub API's `patch` field (the actual diff
    hunk): Sprint 1 reports *what* changed, not the source content itself.
    """

    model_config = ConfigDict(extra="ignore")

    filename: str
    status: str
    additions: int = 0
    deletions: int = 0
    changes: int = 0


class GitHubFetchResult(BaseModel):
    """The full result of fetching one public GitHub issue or pull request."""

    model_config = ConfigDict(extra="ignore")

    kind: Literal["issue", "pull_request"]
    owner: str
    repo: str
    issue: IssueDetails
    pull_request: PullRequestExtra | None = None
    comments: list[IssueComment] = []
    changed_files: list[ChangedFile] | None = None


__all__ = [
    "ChangedFile",
    "GitHubFetchResult",
    "GitHubResourceKind",
    "GitHubUser",
    "IssueComment",
    "IssueDetails",
    "PullRequestExtra",
]
