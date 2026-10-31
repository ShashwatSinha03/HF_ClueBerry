from __future__ import annotations

import clueberry.main as main_module
import pytest
from clueberry.github.models import (
    ChangedFile,
    GitHubFetchResult,
    IssueDetails,
    PullRequestExtra,
)
from clueberry.investigation import (
    Evidence,
    InspectionResult,
    InvalidRepositoryError,
    extract_search_terms,
    github_clone_url,
    target_from_fetch_result,
)
from clueberry.investigation.files import categorize, decode_text, skip_reason, split_lines
from clueberry.investigation.git import InspectionError, TreeEntry
from clueberry.investigation.inspector import _evidence as _make_evidence
from pydantic import ValidationError
from typer.testing import CliRunner

SHA = "a" * 40


def _evidence(**overrides: object) -> Evidence:
    fields: dict[str, object] = {
        "repository": "o/r",
        "commit_sha": SHA,
        "path": "src/app.py",
        "start_line": 1,
        "end_line": 2,
        "text": "a\nb",
        "category": "source",
        "reason": "test",
    }
    fields.update(overrides)
    return Evidence(**fields)


# --- Evidence model ----------------------------------------------------------


def test_evidence_location() -> None:
    assert _evidence().location == "src/app.py:1-2"
    assert _evidence(start_line=3, end_line=3).location == "src/app.py:3"
    history = _evidence(category="history", start_line=None, end_line=None)
    assert history.location == "src/app.py"


@pytest.mark.parametrize(
    "overrides",
    [
        {"commit_sha": "abc123"},
        {"commit_sha": "A" * 40},
        {"path": "/etc/passwd"},
        {"path": "../outside.py"},
        {"path": "src//app.py"},
        {"start_line": 0},
        {"start_line": 5, "end_line": 2},
        {"start_line": None, "end_line": None},
        {"category": "history"},
        {"category": "opinion"},
    ],
)
def test_evidence_rejects_invalid_values(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _evidence(**overrides)


# --- file rules ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("src/app.py", "source"),
        ("latest.py", "source"),
        ("tests/test_app.py", "test"),
        ("pkg/app_test.go", "test"),
        ("web/app.spec.ts", "test"),
        ("src/test/java/AppTest.java", "test"),
        ("README.md", "documentation"),
        ("README", "documentation"),
        ("docs/guide.py", "documentation"),
        ("CHANGELOG", "documentation"),
    ],
)
def test_categorize(path: str, category: str) -> None:
    assert categorize(path) == category


def _entry(path: str, mode: str = "100644", size: int | None = 10, kind: str = "blob") -> TreeEntry:
    return TreeEntry(path=path, mode=mode, object_type=kind, oid="b" * 40, size=size)


@pytest.mark.parametrize(
    ("entry", "reason"),
    [
        (_entry("src/app.py"), None),
        (_entry("bin/run.sh", mode="100755"), None),
        (_entry("link", mode="120000"), "symlink"),
        (_entry("vendored", mode="160000", size=None, kind="commit"), "submodule"),
        (_entry("node_modules/x/index.js"), "excluded_directory"),
        (_entry("Vendor/lib.py"), "excluded_directory"),
        (_entry("yarn.lock"), "generated"),
        (_entry("static/app.min.js"), "generated"),
        (_entry("img/logo.PNG"), "binary"),
        (_entry("big.py", size=1_000_000), "oversized"),
        (_entry("bad\nname.py"), "invalid_path"),
        (_entry("../escape.py"), "invalid_path"),
        (_entry("src/./app.py"), "invalid_path"),
        (_entry("src//app.py"), "invalid_path"),
        (_entry("/etc/passwd"), "invalid_path"),
    ],
)
def test_skip_reason(entry: TreeEntry, reason: str | None) -> None:
    assert skip_reason(entry, max_file_bytes=200_000) == reason


def test_invalid_evidence_becomes_a_clean_inspection_error() -> None:
    with pytest.raises(InspectionError, match="invalid evidence for '../escape.py'"):
        _make_evidence(
            repository="o/r",
            commit_sha=SHA,
            path="../escape.py",
            start_line=1,
            end_line=1,
            text="x",
            category="source",
            reason="test",
        )


def test_decode_text_detects_binary_and_invalid_utf8() -> None:
    assert decode_text(b"hello\n") == "hello\n"
    assert decode_text(b"\xef\xbb\xbfbom\n") == "bom\n"
    assert decode_text(b"abc\x00def") is None
    assert decode_text(b"\xff\xfe\xfa") is None


def test_split_lines_numbers_like_github() -> None:
    assert split_lines("a\r\nb\nc\n") == ["a", "b", "c"]
    assert split_lines("a b") == ["a b"]  # only \n starts a new line
    assert split_lines("") == []


# --- search terms ----------------------------------------------------------------


def test_extract_search_terms_finds_code_like_tokens() -> None:
    terms = extract_search_terms(
        "Crash in `parse_config` when ConfigLoader.load() reads src/app/main.py",
        "See https://example.com/some_path/file.py and e.g. the loadSettings helper.",
    )
    assert "parse_config" in terms
    assert "ConfigLoader.load" in terms
    assert "src/app/main.py" in terms
    assert "loadSettings" in terms
    assert "e.g" not in terms
    assert not any("example.com" in t or "some_path" in t for t in terms)


def test_extract_search_terms_skips_numbers_and_punctuated_fragments() -> None:
    terms = extract_search_terms('Maps `102` to `early-hints`, see `codes.get("processing")`.')
    assert "102" not in terms
    assert "early-hints" in terms
    assert "codes.get" in terms
    assert not any('"' in t or "(" in t for t in terms)


def test_extract_search_terms_is_capped() -> None:
    text = " ".join(f"name_{i}" for i in range(50))
    assert len(extract_search_terms(text)) == 10


# --- target building -----------------------------------------------------------


def _issue(title: str = "Bug in parse_config", body: str | None = None) -> IssueDetails:
    return IssueDetails(
        number=1,
        title=title,
        state="open",
        body=body,
        html_url="https://github.com/o/r/issues/1",
        created_at="2024-01-01T00:00:00Z",
        updated_at="2024-01-01T00:00:00Z",
    )


def test_target_for_pull_request_uses_head_sha_and_live_changed_files() -> None:
    result = GitHubFetchResult(
        kind="pull_request",
        owner="octocat",
        repo="Hello-World",
        issue=_issue(),
        pull_request=PullRequestExtra(base_ref="main", head_ref="fix", head_sha=SHA),
        changed_files=[
            ChangedFile(filename="src/a.py", status="modified"),
            ChangedFile(filename="src/old.py", status="removed"),
        ],
    )
    target = target_from_fetch_result(result, extra_terms=["extra_term"])

    assert target.clone_url == "https://github.com/octocat/Hello-World.git"
    assert target.repository == "octocat/Hello-World"
    assert target.revision == SHA
    assert target.changed_paths == ("src/a.py",)
    assert target.search_terms == ("parse_config", "extra_term")


def test_target_for_issue_uses_default_branch_head() -> None:
    result = GitHubFetchResult(kind="issue", owner="octocat", repo="Hello-World", issue=_issue())
    target = target_from_fetch_result(result)
    assert target.revision == "HEAD"
    assert target.changed_paths == ()


@pytest.mark.parametrize(("owner", "repo"), [("..", "r"), ("o", ".."), ("-o", "r"), ("o", "r/x")])
def test_github_clone_url_rejects_bad_names(owner: str, repo: str) -> None:
    with pytest.raises(InvalidRepositoryError):
        github_clone_url(owner, repo)


def test_pull_request_extra_reads_head_sha_from_api() -> None:
    extra = PullRequestExtra.from_api({"base": {"ref": "main"}, "head": {"ref": "fix", "sha": SHA}})
    assert extra.head_sha == SHA


# --- CLI -------------------------------------------------------------------------


def test_inspect_command_prints_evidence_and_escapes_markup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetched = GitHubFetchResult(kind="issue", owner="octocat", repo="Hello-World", issue=_issue())
    calls: dict[str, object] = {}

    def fake_inspect(clone_url: str, repository: str, **kwargs: object) -> InspectionResult:
        calls.update(clone_url=clone_url, **kwargs)
        return InspectionResult(
            repository=repository,
            commit_sha=SHA,
            requested_revision="HEAD",
            search_terms=["parse_config"],
            files_in_tree=3,
            files_eligible=2,
            files_inspected=2,
            skipped={"binary": 1},
            truncated=False,
            evidence=[_evidence(path="src/[red]app.py", text="def parse_config(): [bold]x[/bold]")],
        )

    monkeypatch.setattr(main_module, "_fetch_or_exit", lambda url: fetched)
    monkeypatch.setattr(main_module, "inspect_repository", fake_inspect)

    result = CliRunner().invoke(
        main_module.app,
        ["inspect", "https://github.com/octocat/Hello-World/issues/1", "--show-text"],
    )

    assert result.exit_code == 0, result.stdout
    assert calls["clone_url"] == "https://github.com/octocat/Hello-World.git"
    assert calls["revision"] == "HEAD"
    assert "src/[red]app.py:1-2" in result.stdout
    assert "[bold]x[/bold]" in result.stdout
    assert "binary=1" in result.stdout
