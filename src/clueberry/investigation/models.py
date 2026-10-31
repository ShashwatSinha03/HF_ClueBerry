from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

EvidenceCategory = Literal["source", "documentation", "test", "history"]

_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class Evidence(BaseModel):
    """One traceable piece of evidence taken from a repository at a fixed commit.

    Snippet evidence (source/documentation/test) carries a 1-based, inclusive
    line range whose text is exactly those lines of `path` at `commit_sha`.
    History evidence describes commits touching `path` and has no line range.
    """

    model_config = ConfigDict(frozen=True)

    repository: str
    commit_sha: str
    path: str
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    text: str
    category: EvidenceCategory
    reason: str

    @field_validator("commit_sha")
    @classmethod
    def _full_sha(cls, value: str) -> str:
        if not _SHA_RE.match(value):
            raise ValueError("commit_sha must be a full lowercase hex git object id")
        return value

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        segments = value.split("/")
        if value.startswith("/") or "\x00" in value or any(s in ("", ".", "..") for s in segments):
            raise ValueError(f"path must be a normalized relative repository path: {value!r}")
        return value

    @model_validator(mode="after")
    def _line_range_matches_category(self) -> Evidence:
        if self.category == "history":
            if self.start_line is not None or self.end_line is not None:
                raise ValueError("history evidence has no line range")
        elif self.start_line is None or self.end_line is None:
            raise ValueError(f"{self.category} evidence requires start_line and end_line")
        elif self.end_line < self.start_line:
            raise ValueError("end_line must be >= start_line")
        return self

    @property
    def location(self) -> str:
        if self.start_line is None:
            return self.path
        if self.start_line == self.end_line:
            return f"{self.path}:{self.start_line}"
        return f"{self.path}:{self.start_line}-{self.end_line}"


class InspectionLimits(BaseModel):
    """Bounds applied to every repository inspection."""

    model_config = ConfigDict(frozen=True)

    git_timeout_seconds: float = Field(default=120.0, gt=0)
    history_depth: int = Field(default=10, ge=1, le=100)
    max_repository_bytes: int = Field(default=250_000_000, gt=0)
    max_tree_entries: int = Field(default=100_000, gt=0)
    max_files_inspected: int = Field(default=300, gt=0)
    max_file_bytes: int = Field(default=200_000, gt=0)
    max_total_bytes: int = Field(default=20_000_000, gt=0)
    max_evidence: int = Field(default=40, gt=0)
    max_snippets_per_file: int = Field(default=3, gt=0)
    context_lines: int = Field(default=3, ge=0)
    overview_lines: int = Field(default=20, gt=0)
    max_history_files: int = Field(default=3, ge=0)
    max_history_commits: int = Field(default=5, gt=0)


class InspectionResult(BaseModel):
    """Everything collected from one repository inspection."""

    repository: str
    commit_sha: str
    requested_revision: str
    search_terms: list[str]
    files_in_tree: int
    files_eligible: int
    files_inspected: int
    skipped: dict[str, int]
    truncated: bool
    evidence: list[Evidence]
