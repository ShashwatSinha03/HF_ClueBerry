from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

import clueberry.investigation.git as git_module
import pytest
from clueberry.investigation import (
    GitTimeoutError,
    InspectionLimits,
    InspectionResult,
    InvalidRepositoryError,
    RepositoryFetchError,
    RepositoryLimitError,
    inspect_repository,
)
from clueberry.investigation.git import validate_clone_url
from conftest import FixtureRepo

CALC = (
    '"""Calculator helpers."""\n'
    "\n"
    "\n"
    "def add_numbers(a, b):\n"  # line 4
    "    return a + b\n"
    "\n"
    "\n"
    "def subtract_numbers(a, b):\n"  # line 8
    "    return a - b\n"
)
TEST_CALC = (
    "from src.calc import add_numbers\n\n\ndef test_add():\n    assert add_numbers(1, 2) == 3\n"
)
README = "# Calc\n\nA tiny calculator. Use add_numbers to add.\n"

MakeRepo = Callable[..., FixtureRepo]


@pytest.fixture
def calc_repo(make_repo: MakeRepo) -> tuple[FixtureRepo, str]:
    repo = make_repo()
    repo.write("src/calc.py", CALC)
    repo.write("tests/test_calc.py", TEST_CALC)
    repo.write("README.md", README)
    return repo, repo.commit("initial calculator")


@pytest.fixture
def workspaces(tmp_path: Path) -> Path:
    root = tmp_path / "workspaces"
    root.mkdir()
    return root


def _inspect(repo: FixtureRepo, workspaces: Path, **kwargs: object) -> InspectionResult:
    return inspect_repository(
        repo.url, "fixture/calc", allow_local=True, workspace_root=workspaces, **kwargs
    )


def _snippets(result: InspectionResult) -> list:
    return [e for e in result.evidence if e.category != "history"]


# --- successful inspection, accuracy and traceability ----------------------


def test_collects_evidence_with_exact_paths_and_lines(
    calc_repo: tuple[FixtureRepo, str], workspaces: Path
) -> None:
    repo, sha = calc_repo
    result = _inspect(repo, workspaces, search_terms=["add_numbers"])

    assert result.commit_sha == sha
    assert {e.path for e in _snippets(result)} == {"src/calc.py", "tests/test_calc.py", "README.md"}

    for item in _snippets(result):
        file_lines = (repo.path / item.path).read_text().split("\n")
        assert item.text == "\n".join(file_lines[item.start_line - 1 : item.end_line])

    calc = next(e for e in result.evidence if e.path == "src/calc.py")
    assert calc.category == "source"
    assert calc.start_line <= 4 <= calc.end_line
    assert "def add_numbers(a, b):" in calc.text


def test_categories_are_assigned(calc_repo: tuple[FixtureRepo, str], workspaces: Path) -> None:
    repo, _ = calc_repo
    result = _inspect(repo, workspaces, search_terms=["add_numbers"])
    categories = {e.path: e.category for e in _snippets(result)}
    assert categories == {
        "src/calc.py": "source",
        "tests/test_calc.py": "test",
        "README.md": "documentation",
    }


def test_evidence_is_traceable_to_an_older_commit(make_repo: MakeRepo, workspaces: Path) -> None:
    repo = make_repo()
    repo.write("src/version.py", "VERSION_MARKER = 'one'\n")
    first = repo.commit("v1")
    repo.write("src/version.py", "VERSION_MARKER = 'two'\n")
    second = repo.commit("v2")

    old = _inspect(repo, workspaces, revision=first, search_terms=["VERSION_MARKER"])
    new = _inspect(repo, workspaces, revision="HEAD", search_terms=["VERSION_MARKER"])

    assert old.commit_sha == first and new.commit_sha == second
    assert all(e.commit_sha == first for e in old.evidence)
    assert _snippets(old)[0].text == "VERSION_MARKER = 'one'"
    assert _snippets(new)[0].text == "VERSION_MARKER = 'two'"


def test_default_revision_resolves_to_head_sha(
    calc_repo: tuple[FixtureRepo, str], workspaces: Path
) -> None:
    repo, sha = calc_repo
    result = _inspect(repo, workspaces)
    assert result.requested_revision == "HEAD"
    assert result.commit_sha == sha


def test_pr_changed_files_are_prioritized(
    calc_repo: tuple[FixtureRepo, str], workspaces: Path
) -> None:
    repo, _ = calc_repo
    result = _inspect(repo, workspaces, changed_paths=["src/calc.py"])

    first = result.evidence[0]
    assert first.path == "src/calc.py"
    assert first.reason.startswith("changed in pull request")
    related = next(e for e in result.evidence if e.path == "tests/test_calc.py")
    assert "test related to changed 'calc'" in related.reason


def test_history_evidence_lists_commits_touching_a_changed_file(
    make_repo: MakeRepo, workspaces: Path
) -> None:
    repo = make_repo()
    repo.write("src/calc.py", CALC)
    first = repo.commit("add calculator")
    repo.write("src/calc.py", CALC + "\n\ndef multiply(a, b):\n    return a * b\n")
    second = repo.commit("add multiply")

    result = _inspect(repo, workspaces, changed_paths=["src/calc.py"])
    history = [e for e in result.evidence if e.category == "history"]

    assert len(history) == 1
    assert history[0].path == "src/calc.py"
    assert history[0].start_line is None and history[0].end_line is None
    assert history[0].text.splitlines()[0].startswith(f"{second} ")
    assert first in history[0].text
    assert "add multiply" in history[0].text


def test_shallow_boundary_commits_are_never_reported_as_file_changes(
    make_repo: MakeRepo, workspaces: Path
) -> None:
    repo = make_repo()
    repo.write("untouched.py", "STABLE = 1\n")
    repo.write("a.py", "A = 1\n")
    repo.commit("c1: add files")
    repo.write("a.py", "A = 2\n")
    repo.commit("c2: edit a")
    repo.write("a.py", "A = 3\n")
    boundary = repo.commit("c3: edit a")  # oldest commit fetched at depth 2
    repo.write("other.py", "OTHER = 1\n")
    head = repo.commit("c4: add other")

    result = _inspect(
        repo,
        workspaces,
        changed_paths=["untouched.py", "other.py"],
        limits=InspectionLimits(history_depth=2),
    )
    history = {e.path: e.text for e in result.evidence if e.category == "history"}

    # Without the fix, git attributes untouched.py to the boundary commit c3.
    assert "untouched.py" not in history
    assert history["other.py"].startswith(f"{head} ")
    assert all(boundary not in text for text in history.values())


# --- missing or invalid repositories ---------------------------------------


def test_missing_repository_raises_fetch_error(tmp_path: Path, workspaces: Path) -> None:
    with pytest.raises(RepositoryFetchError):
        inspect_repository(
            (tmp_path / "does-not-exist").as_uri(),
            "fixture/missing",
            allow_local=True,
            workspace_root=workspaces,
        )


def test_unknown_commit_raises_fetch_error(
    calc_repo: tuple[FixtureRepo, str], workspaces: Path
) -> None:
    repo, _ = calc_repo
    with pytest.raises(RepositoryFetchError):
        _inspect(repo, workspaces, revision="0" * 40)


@pytest.mark.parametrize(
    "revision",
    ["main", "--upload-pack=touch /tmp/pwned", "HEAD~1", "refs/heads/main", "abc123", ""],
)
def test_rejects_unsafe_or_unsupported_revisions(
    calc_repo: tuple[FixtureRepo, str], workspaces: Path, revision: str
) -> None:
    repo, _ = calc_repo
    with pytest.raises(InvalidRepositoryError):
        _inspect(repo, workspaces, revision=revision)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.com/owner/repo.git",
        "https://github.com.evil.com/owner/repo.git",
        "https://user@github.com/owner/repo.git",
        "https://github.com:8443/owner/repo.git",
        "https://github.com/owner/repo.git?upload-pack=x",
        "https://github.com/owner/repo/extra.git",
        "https://github.com/../repo.git",
        "ssh://git@github.com/owner/repo.git",
        "git@github.com:owner/repo.git",
        "http://github.com/owner/repo.git",
        "ext::sh -c touch% /tmp/pwned",
    ],
)
def test_rejects_unsupported_repository_urls(url: str, workspaces: Path) -> None:
    with pytest.raises(InvalidRepositoryError):
        inspect_repository(url, "x/y", workspace_root=workspaces)


def test_accepts_github_https_urls() -> None:
    assert validate_clone_url("https://github.com/octocat/Hello-World.git") == "https"
    assert validate_clone_url("https://github.com/octocat/Hello-World") == "https"


def test_file_urls_rejected_unless_explicitly_allowed(
    calc_repo: tuple[FixtureRepo, str], workspaces: Path
) -> None:
    repo, _ = calc_repo
    with pytest.raises(InvalidRepositoryError):
        inspect_repository(repo.url, "fixture/calc", workspace_root=workspaces)


# --- exclusions and limits ---------------------------------------------------


def test_binary_generated_and_dependency_files_are_excluded(
    make_repo: MakeRepo, workspaces: Path
) -> None:
    repo = make_repo()
    repo.write("src/app.py", "TARGET_TERM = 1\n")
    repo.write("assets/logo.png", b"\x89PNG\r\n\x1a\n\x00\x00TARGET_TERM")
    repo.write("data/blob.dat", b"TARGET_TERM\x00\x01\x02")
    repo.write("node_modules/lib/index.js", "const TARGET_TERM = 1;\n")
    repo.write("package-lock.json", '{"TARGET_TERM": true}\n')
    repo.write("static/app.min.js", "var TARGET_TERM=1;\n")
    repo.commit("mixed content")

    result = _inspect(repo, workspaces, search_terms=["TARGET_TERM"])

    assert {e.path for e in _snippets(result)} == {"src/app.py"}
    assert result.skipped == {"binary": 2, "excluded_directory": 1, "generated": 2}


def test_oversized_files_are_excluded(make_repo: MakeRepo, workspaces: Path) -> None:
    repo = make_repo()
    repo.write("small.py", "TARGET_TERM = 1\n")
    repo.write("big.py", "TARGET_TERM = 1\n" + "# padding\n" * 50)
    repo.commit("sizes")

    result = _inspect(
        repo, workspaces, search_terms=["TARGET_TERM"], limits=InspectionLimits(max_file_bytes=100)
    )

    assert {e.path for e in _snippets(result)} == {"small.py"}
    assert result.skipped == {"oversized": 1}


def test_file_count_limit_truncates_inspection(make_repo: MakeRepo, workspaces: Path) -> None:
    repo = make_repo()
    for i in range(10):
        repo.write(f"src/module_{i}.py", f"TARGET_TERM = {i}\n")
    repo.commit("many files")

    result = _inspect(
        repo,
        workspaces,
        search_terms=["TARGET_TERM"],
        limits=InspectionLimits(max_files_inspected=3),
    )

    assert result.files_eligible == 10
    assert result.files_inspected == 3
    assert result.truncated is True
    assert len({e.path for e in _snippets(result)}) == 3


def test_total_bytes_limit_truncates_inspection(make_repo: MakeRepo, workspaces: Path) -> None:
    repo = make_repo()
    for i in range(5):
        repo.write(f"src/module_{i}.py", f"TARGET_TERM = {i}\n")  # 16 bytes each
    repo.commit("many files")

    result = _inspect(
        repo, workspaces, search_terms=["TARGET_TERM"], limits=InspectionLimits(max_total_bytes=40)
    )

    assert result.files_inspected == 2
    assert result.truncated is True


def test_evidence_limit_caps_results(make_repo: MakeRepo, workspaces: Path) -> None:
    repo = make_repo()
    for i in range(10):
        repo.write(f"src/module_{i}.py", f"TARGET_TERM = {i}\n")
    repo.commit("many files")

    result = _inspect(
        repo,
        workspaces,
        search_terms=["TARGET_TERM"],
        limits=InspectionLimits(max_evidence=4, max_history_files=1),
    )

    assert len(result.evidence) <= 4
    assert result.truncated is True


def test_repository_size_limit(calc_repo: tuple[FixtureRepo, str], workspaces: Path) -> None:
    repo, _ = calc_repo
    with pytest.raises(RepositoryLimitError):
        _inspect(repo, workspaces, limits=InspectionLimits(max_repository_bytes=1))
    assert list(workspaces.iterdir()) == []


def test_tree_entry_limit(calc_repo: tuple[FixtureRepo, str], workspaces: Path) -> None:
    repo, _ = calc_repo
    with pytest.raises(RepositoryLimitError):
        _inspect(repo, workspaces, limits=InspectionLimits(max_tree_entries=2))
    assert list(workspaces.iterdir()) == []


# --- safety ---------------------------------------------------------------


def test_symlinks_are_never_followed(make_repo: MakeRepo, tmp_path: Path, workspaces: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("TOP_SECRET_VALUE\n")

    repo = make_repo()
    repo.write("src/app.py", "print('hello')\n")
    repo.symlink("absolute_link.txt", str(secret))
    repo.symlink("relative_link.txt", "../outside/secret.txt")
    repo.commit("symlinks")

    result = _inspect(
        repo,
        workspaces,
        search_terms=["TOP_SECRET_VALUE", "secret.txt"],
        changed_paths=["absolute_link.txt", "relative_link.txt"],
    )

    assert result.skipped == {"symlink": 2}
    assert all("link" not in e.path for e in result.evidence)
    assert all("TOP_SECRET_VALUE" not in e.text for e in result.evidence)
    assert all("secret.txt" not in e.text for e in result.evidence)


def test_workspace_removed_after_success(
    calc_repo: tuple[FixtureRepo, str], workspaces: Path
) -> None:
    repo, _ = calc_repo
    _inspect(repo, workspaces, search_terms=["add_numbers"])
    assert list(workspaces.iterdir()) == []


def test_workspace_removed_after_failure(
    calc_repo: tuple[FixtureRepo, str], workspaces: Path
) -> None:
    repo, _ = calc_repo
    with pytest.raises(RepositoryFetchError):
        _inspect(repo, workspaces, revision="f" * 40)
    assert list(workspaces.iterdir()) == []


def test_git_timeout_is_reported_and_workspace_removed(
    calc_repo: tuple[FixtureRepo, str], workspaces: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = calc_repo
    real_run = subprocess.run

    def slow_fetch(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        if "fetch" in cmd:
            raise subprocess.TimeoutExpired(cmd, timeout=1)
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(git_module.subprocess, "run", slow_fetch)
    with pytest.raises(GitTimeoutError):
        _inspect(repo, workspaces)
    assert list(workspaces.iterdir()) == []


def test_git_never_receives_caller_environment(
    calc_repo: tuple[FixtureRepo, str], workspaces: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo, _ = calc_repo
    monkeypatch.setenv("CLUEBERRY_GITHUB_TOKEN", "ghp_should_not_leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws_should_not_leak")
    monkeypatch.setenv("GIT_SSH_COMMAND", "touch /tmp/pwned")

    captured: list[dict[str, str]] = []
    real_run = subprocess.run

    def recording_run(cmd: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        captured.append(dict(kwargs["env"]))  # type: ignore[arg-type]
        return real_run(cmd, **kwargs)

    monkeypatch.setattr(git_module.subprocess, "run", recording_run)
    _inspect(repo, workspaces, search_terms=["add_numbers"])

    assert captured
    for env in captured:
        assert set(env) <= {
            "PATH",
            "HOME",
            "GIT_CONFIG_NOSYSTEM",
            "GIT_CONFIG_GLOBAL",
            "GIT_TERMINAL_PROMPT",
            "GIT_ALLOW_PROTOCOL",
            "GIT_LITERAL_PATHSPECS",
            "LC_ALL",
        }
        assert env["GIT_ALLOW_PROTOCOL"] == "file"
        assert not any("should_not_leak" in value for value in env.values())
