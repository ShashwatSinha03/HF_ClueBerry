from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from clueberry.github.models import GitHubFetchResult

from .files import categorize, decode_text, skip_reason, split_lines
from .git import GitWorkspace, InspectionError, TreeEntry, github_clone_url
from .models import Evidence, InspectionLimits, InspectionResult


def _evidence(**fields: object) -> Evidence:
    try:
        return Evidence.model_validate(fields)
    except ValidationError as exc:
        raise InspectionError(
            f"Repository produced invalid evidence for {fields.get('path')!r}: "
            f"{exc.errors()[0]['msg']}"
        ) from exc


_URL_RE = re.compile(r"https?://\S+")
_CODE_SPAN_RE = re.compile(r"`([^`\n]{2,100})`")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_./:-]+$")
_TERM_PATTERNS = (
    re.compile(r"(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9]{1,8}\b"),  # paths
    re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+\b"),  # dotted.names
    re.compile(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b"),  # snake_case
    re.compile(r"\b[a-z]+[A-Z][A-Za-z0-9]*\b"),  # camelCase
    re.compile(r"\b[A-Z][a-z0-9]+[A-Z][A-Za-z0-9]*\b"),  # PascalCase
)
_MAX_TERMS = 10

# Lower sorts first.
_PRIORITY_CHANGED = 0
_PRIORITY_MENTIONED = 1
_PRIORITY_RELATED_TEST = 2
_PRIORITY_README = 3
_PRIORITY_SEARCH = 5
_CATEGORY_ORDER = {"source": 0, "test": 1, "documentation": 2}


def extract_search_terms(*texts: str, max_terms: int = _MAX_TERMS) -> list[str]:
    """Pull code-like tokens (identifiers, dotted names, file paths) out of free text.

    This is a purely lexical heuristic used to decide which files to look at;
    it does not interpret or extract claims.
    """
    terms: list[str] = []

    def add(candidate: str) -> None:
        candidate = candidate.strip().strip(".,:;()[]{}\"'")
        if not 3 <= len(candidate) <= 100 or candidate in terms:
            return
        if not _TOKEN_RE.match(candidate) or not re.search(r"[A-Za-z]", candidate):
            return  # punctuation-laden fragments and bare numbers match too much noise
        if "." in candidate and "/" not in candidate:
            if any(len(part) < 2 for part in candidate.split(".")):
                return  # e.g. "e.g", "i.e"
        terms.append(candidate)

    for text in texts:
        text = _URL_RE.sub(" ", text or "")
        for span in _CODE_SPAN_RE.findall(text):
            add(span)
        for pattern in _TERM_PATTERNS:
            for match in pattern.findall(text):
                add(match)
    return terms[:max_terms]


@dataclass(frozen=True)
class InvestigationTarget:
    """What to inspect, derived from a Sprint 1 GitHub fetch result."""

    clone_url: str
    repository: str
    revision: str
    changed_paths: tuple[str, ...]
    search_terms: tuple[str, ...]


def target_from_fetch_result(
    result: GitHubFetchResult, extra_terms: Sequence[str] = ()
) -> InvestigationTarget:
    revision = "HEAD"
    if result.pull_request is not None and result.pull_request.head_sha:
        revision = result.pull_request.head_sha

    changed_paths = tuple(
        changed.filename for changed in result.changed_files or () if changed.status != "removed"
    )
    terms = extract_search_terms(result.issue.title, result.issue.body or "")
    for term in extra_terms:
        if term and term not in terms:
            terms.append(term)

    return InvestigationTarget(
        clone_url=github_clone_url(result.owner, result.repo),
        repository=f"{result.owner}/{result.repo}",
        revision=revision,
        changed_paths=changed_paths,
        search_terms=tuple(terms),
    )


@dataclass
class _Candidate:
    entry: TreeEntry
    category: str
    priority: int
    reason: str


def _stem(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.split(".", 1)[0].lower()


def _plan(
    eligible: list[TreeEntry], changed_paths: Sequence[str], search_terms: Sequence[str]
) -> list[_Candidate]:
    changed = set(changed_paths)
    path_terms = [t for t in search_terms if "/" in t or re.search(r"\.[A-Za-z0-9]{1,8}$", t)]
    changed_source_stems = {
        _stem(p) for p in changed if categorize(p) == "source" and len(_stem(p)) >= 3
    }

    candidates: list[_Candidate] = []
    for entry in eligible:
        category = categorize(entry.path)
        name = entry.path.rsplit("/", 1)[-1].lower()
        mentioned = next(
            (t for t in path_terms if entry.path == t or entry.path.endswith("/" + t)), None
        )
        related_to = next(
            (s for s in changed_source_stems if category == "test" and s in name), None
        )

        if entry.path in changed:
            candidate = _Candidate(entry, category, _PRIORITY_CHANGED, "changed in pull request")
        elif mentioned:
            candidate = _Candidate(
                entry, category, _PRIORITY_MENTIONED, f"path {mentioned!r} mentioned in issue/PR"
            )
        elif related_to:
            candidate = _Candidate(
                entry, category, _PRIORITY_RELATED_TEST, f"test related to changed {related_to!r}"
            )
        elif "/" not in entry.path and name.startswith("readme"):
            candidate = _Candidate(entry, category, _PRIORITY_README, "project README")
        else:
            if not search_terms:
                continue  # nothing could make this file evidence, so don't read it
            candidate = _Candidate(entry, category, _PRIORITY_SEARCH, "matches search term")
        candidates.append(candidate)

    candidates.sort(key=lambda c: (c.priority, _CATEGORY_ORDER[c.category], c.entry.path))
    return candidates


def _windows(
    match_lines: list[int], line_count: int, context: int, limit: int
) -> list[tuple[int, int]]:
    windows: list[tuple[int, int]] = []
    for line in match_lines:
        start, end = max(1, line - context), min(line_count, line + context)
        if windows and start <= windows[-1][1] + 1:
            windows[-1] = (windows[-1][0], max(windows[-1][1], end))
        else:
            windows.append((start, end))
    return windows[:limit]


def inspect_repository(
    clone_url: str,
    repository: str,
    *,
    revision: str = "HEAD",
    changed_paths: Sequence[str] = (),
    search_terms: Sequence[str] = (),
    limits: InspectionLimits | None = None,
    allow_local: bool = False,
    workspace_root: Path | None = None,
) -> InspectionResult:
    """Shallow-fetch a repository at one commit and collect traceable evidence.

    No repository code is executed and no working tree is checked out:
    files are listed and read directly from git's object database inside a
    temporary directory that is always removed afterwards.
    """
    limits = limits or InspectionLimits()
    skipped: Counter[str] = Counter()
    truncated = False
    evidence: list[Evidence] = []

    with GitWorkspace(
        clone_url, limits=limits, allow_local=allow_local, workspace_root=workspace_root
    ) as workspace:
        sha = workspace.fetch(revision)
        tree = workspace.list_tree(sha)

        eligible: list[TreeEntry] = []
        for entry in tree:
            reason = skip_reason(entry, limits.max_file_bytes)
            if reason:
                skipped[reason] += 1
            else:
                eligible.append(entry)

        candidates = _plan(eligible, changed_paths, search_terms)

        selected: list[_Candidate] = []
        total_bytes = 0
        for candidate in candidates:
            size = candidate.entry.size or 0
            if (
                len(selected) >= limits.max_files_inspected
                or total_bytes + size > limits.max_total_bytes
            ):
                truncated = True
                break
            selected.append(candidate)
            total_bytes += size

        blobs = workspace.read_blobs([c.entry.oid for c in selected])

        snippet_budget = max(1, limits.max_evidence - limits.max_history_files)
        match_counts: dict[str, int] = {}
        for candidate in selected:
            text = decode_text(blobs.get(candidate.entry.oid, b""))
            if text is None:
                skipped["binary"] += 1
                continue
            lines = split_lines(text)
            if not lines:
                continue

            matched_terms = [t for t in search_terms if t and t in text]
            match_lines = [
                n for n, line in enumerate(lines, start=1) if any(t in line for t in matched_terms)
            ]
            match_counts[candidate.entry.path] = len(match_lines)

            if match_lines:
                windows = _windows(
                    match_lines, len(lines), limits.context_lines, limits.max_snippets_per_file
                )
                quoted = ", ".join(repr(t) for t in matched_terms[:3])
                if candidate.priority == _PRIORITY_SEARCH:
                    reason = f"matches search term {quoted}"
                else:
                    reason = f"{candidate.reason}; matches {quoted}"
            elif candidate.priority < _PRIORITY_SEARCH:
                windows = [(1, min(len(lines), limits.overview_lines))]
                reason = f"{candidate.reason} (file overview)"
            else:
                continue

            for start, end in windows:
                if len(evidence) >= snippet_budget:
                    truncated = True
                    break
                evidence.append(
                    _evidence(
                        repository=repository,
                        commit_sha=sha,
                        path=candidate.entry.path,
                        start_line=start,
                        end_line=end,
                        text="\n".join(lines[start - 1 : end]),
                        category=candidate.category,
                        reason=reason,
                    )
                )

        history_paths = [c.entry.path for c in selected if c.priority == _PRIORITY_CHANGED]
        history_paths += sorted(
            (p for p, n in match_counts.items() if n and p not in history_paths),
            key=lambda p: -match_counts[p],
        )
        for path in history_paths[: limits.max_history_files]:
            commits = workspace.file_history(sha, path, limits.max_history_commits)
            if not commits:
                continue
            evidence.append(
                _evidence(
                    repository=repository,
                    commit_sha=sha,
                    path=path,
                    text="\n".join(f"{c.sha} {c.date} {c.subject}" for c in commits),
                    category="history",
                    reason=(
                        f"recent commits touching this file "
                        f"(shallow history, depth {limits.history_depth})"
                    ),
                )
            )

    return InspectionResult(
        repository=repository,
        commit_sha=sha,
        requested_revision=revision,
        search_terms=list(search_terms),
        files_in_tree=len(tree),
        files_eligible=len(eligible),
        files_inspected=len(selected),
        skipped=dict(sorted(skipped.items())),
        truncated=truncated,
        evidence=evidence,
    )
