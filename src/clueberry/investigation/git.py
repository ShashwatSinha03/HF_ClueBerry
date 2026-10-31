from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from urllib.parse import urlsplit

from .models import InspectionLimits

_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_PULL_REF_RE = re.compile(r"^refs/pull/[1-9][0-9]{0,9}/head$")
_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$")
_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+$")

# Applied to every git invocation, on top of the scrubbed environment.
_SAFE_GIT_CONFIG = (
    "-c",
    f"core.hooksPath={os.devnull}",
    "-c",
    "credential.helper=",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "protocol.version=2",
)


class InspectionError(RuntimeError):
    """Base class for repository inspection failures."""


class InvalidRepositoryError(InspectionError):
    """The repository URL or revision is not one Clueberry will fetch."""


class RepositoryFetchError(InspectionError):
    """The repository or revision could not be fetched (missing, private, or unknown)."""


class RepositoryLimitError(InspectionError):
    """The repository exceeds a configured inspection limit."""


class GitTimeoutError(InspectionError):
    """A git command exceeded its time limit."""


class GitUnavailableError(InspectionError):
    """No git executable was found."""


class _GitCommandError(InspectionError):
    def __init__(self, command: str, returncode: int, stderr: str) -> None:
        super().__init__(f"git {command} failed with exit code {returncode}: {stderr}")
        self.stderr = stderr


@dataclass(frozen=True)
class TreeEntry:
    path: str
    mode: str
    object_type: str
    oid: str
    size: int | None


@dataclass(frozen=True)
class CommitSummary:
    sha: str
    date: str
    subject: str


def github_clone_url(owner: str, repo: str) -> str:
    """Build the only kind of remote URL Clueberry fetches in normal use."""
    if not _OWNER_RE.match(owner) or not _REPO_RE.match(repo) or repo in (".", ".."):
        raise InvalidRepositoryError(f"Invalid GitHub repository name: {owner!r}/{repo!r}")
    return f"https://github.com/{owner}/{repo}.git"


def validate_clone_url(url: str, *, allow_local: bool = False) -> str:
    """Return the git transport to allow for `url`, or raise InvalidRepositoryError.

    Only https://github.com/{owner}/{repo}(.git) is accepted. `file://` URLs
    are accepted only when `allow_local` is set (used by the test suite's
    local fixture repositories).
    """
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as exc:
        raise InvalidRepositoryError(f"Invalid repository URL: {url!r}") from exc

    if parts.scheme == "https":
        segments = parts.path.strip("/").split("/")
        if (
            parts.hostname == "github.com"
            and port is None
            and not parts.username
            and not parts.password
            and not parts.query
            and not parts.fragment
            and len(segments) == 2
        ):
            owner, repo = segments[0], segments[1].removesuffix(".git")
            github_clone_url(owner, repo)
            return "https"

    if allow_local and parts.scheme == "file" and not parts.netloc:
        return "file"

    raise InvalidRepositoryError(f"Unsupported repository URL: {url!r}")


def validate_revision(revision: str) -> None:
    """Accept only HEAD, a full commit SHA, or a GitHub pull-request head ref.

    Branch names are never accepted: they are attacker-controllable strings,
    and refusing them removes any chance of them being read as git options.
    """
    if revision == "HEAD" or _SHA_RE.match(revision) or _PULL_REF_RE.match(revision):
        return
    raise InvalidRepositoryError(f"Unsupported revision: {revision!r}")


class GitWorkspace:
    """A temporary, bare git repository holding one shallow-fetched commit.

    Repository content is read straight from the object database (`ls-tree`,
    `cat-file`); no working tree is ever checked out, so no repository file --
    including symlinks -- is written to disk or followed, and no checkout
    filters or hooks run. The temporary directory is removed on exit, whether
    or not an error occurred.
    """

    def __init__(
        self,
        clone_url: str,
        *,
        limits: InspectionLimits,
        allow_local: bool = False,
        workspace_root: Path | None = None,
    ) -> None:
        self._protocol = validate_clone_url(clone_url, allow_local=allow_local)
        git = shutil.which("git")
        if git is None:
            raise GitUnavailableError("git executable not found on PATH")
        self._git = git
        self._url = clone_url
        self._limits = limits
        self._workspace_root = workspace_root
        self._tmp: tempfile.TemporaryDirectory[str] | None = None
        self._home = Path()
        self._repo = Path()

    @property
    def path(self) -> Path:
        if self._tmp is None:
            raise RuntimeError("workspace is not open")
        return Path(self._tmp.name)

    def __enter__(self) -> GitWorkspace:
        self._tmp = tempfile.TemporaryDirectory(prefix="clueberry-", dir=self._workspace_root)
        try:
            root = Path(self._tmp.name)
            self._home = root / "home"
            self._home.mkdir()
            self._repo = root / "repo.git"
            self._run(["init", "--bare", "--quiet", str(self._repo)])
        except BaseException:
            self.close()
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._tmp is not None:
            self._tmp.cleanup()
            self._tmp = None

    def _env(self) -> dict[str, str]:
        # Built from scratch: nothing from the caller's environment (tokens,
        # credentials, proxies, git config) reaches git except PATH.
        return {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(self._home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_ALLOW_PROTOCOL": self._protocol,
            "GIT_LITERAL_PATHSPECS": "1",
            "LC_ALL": "C",
        }

    def _run(self, args: list[str], *, input_bytes: bytes | None = None) -> bytes:
        try:
            completed = subprocess.run(
                [self._git, *_SAFE_GIT_CONFIG, *args],
                input=input_bytes,
                capture_output=True,
                env=self._env(),
                cwd=self._home,
                timeout=self._limits.git_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise GitTimeoutError(
                f"git {args[0]} timed out after {self._limits.git_timeout_seconds:g}s"
            ) from exc
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", "replace").strip()[:500]
            raise _GitCommandError(args[0], completed.returncode, stderr)
        return completed.stdout

    def _git_dir_args(self, *args: str) -> list[str]:
        return ["--git-dir", str(self._repo), *args]

    def fetch(self, revision: str) -> str:
        """Shallow-fetch `revision` and return the resolved full commit SHA."""
        validate_revision(revision)
        try:
            self._run(
                self._git_dir_args(
                    "fetch",
                    "--quiet",
                    "--no-tags",
                    "--no-recurse-submodules",
                    f"--depth={self._limits.history_depth}",
                    "--end-of-options",
                    self._url,
                    revision,
                )
            )
            sha = (
                self._run(self._git_dir_args("rev-parse", "--verify", "FETCH_HEAD^{commit}"))
                .decode("ascii")
                .strip()
            )
        except _GitCommandError as exc:
            raise RepositoryFetchError(
                f"Could not fetch {revision!r} from {self._url}: {exc.stderr}"
            ) from exc

        if _SHA_RE.match(revision) and sha != revision:
            raise RepositoryFetchError(f"Fetched commit {sha} does not match requested {revision}")

        size = self.repository_size()
        if size > self._limits.max_repository_bytes:
            raise RepositoryLimitError(
                f"Fetched repository data is {size} bytes, over the "
                f"{self._limits.max_repository_bytes}-byte limit"
            )
        return sha

    def repository_size(self) -> int:
        total = 0
        for dirpath, _dirnames, filenames in os.walk(self._repo, followlinks=False):
            for name in filenames:
                total += os.lstat(os.path.join(dirpath, name)).st_size
        return total

    def list_tree(self, sha: str) -> list[TreeEntry]:
        output = self._run(self._git_dir_args("ls-tree", "-r", "-l", "-z", "--full-tree", sha))
        entries: list[TreeEntry] = []
        for raw in output.split(b"\0"):
            if not raw:
                continue
            meta, _, raw_path = raw.partition(b"\t")
            mode, object_type, oid, size = meta.decode("ascii").split()
            entries.append(
                TreeEntry(
                    path=raw_path.decode("utf-8", "replace"),
                    mode=mode,
                    object_type=object_type,
                    oid=oid,
                    size=int(size) if size.isdigit() else None,
                )
            )
            if len(entries) > self._limits.max_tree_entries:
                raise RepositoryLimitError(
                    f"Repository tree has more than {self._limits.max_tree_entries} entries"
                )
        return entries

    def read_blobs(self, oids: list[str]) -> dict[str, bytes]:
        """Read blob contents by object id in a single `cat-file --batch` call."""
        if not oids:
            return {}
        for oid in oids:
            if not _SHA_RE.match(oid):
                raise ValueError(f"Not an object id: {oid!r}")
        output = self._run(
            self._git_dir_args("cat-file", "--batch"),
            input_bytes="".join(f"{oid}\n" for oid in oids).encode("ascii"),
        )
        blobs: dict[str, bytes] = {}
        pos = 0
        while pos < len(output):
            header_end = output.index(b"\n", pos)
            header = output[pos:header_end].decode("ascii").split()
            pos = header_end + 1
            if len(header) != 3:
                continue  # "<oid> missing"
            oid, _object_type, size = header[0], header[1], int(header[2])
            blobs[oid] = output[pos : pos + size]
            pos += size + 1
        return blobs

    def _shallow_boundary(self) -> set[str]:
        shallow = self._repo / "shallow"
        if not shallow.is_file():
            return set()
        return set(shallow.read_text(encoding="ascii").split())

    def file_history(self, sha: str, path: str, max_commits: int) -> list[CommitSummary]:
        """Commits within the fetched history that changed `path`.

        Shallow-boundary commits are excluded: their parents weren't fetched,
        so git reports them as adding every file, whether or not they did.
        """
        boundary = self._shallow_boundary()
        output = self._run(
            self._git_dir_args(
                "log",
                f"--max-count={max_commits}",
                "--format=%H%x1f%ad%x1f%s",
                "--date=short",
                sha,
                "--",
                path,
            )
        )
        commits: list[CommitSummary] = []
        for line in output.decode("utf-8", "replace").splitlines():
            parts = line.split("\x1f")
            if len(parts) == 3 and parts[0] not in boundary:
                commits.append(CommitSummary(sha=parts[0], date=parts[1], subject=parts[2][:200]))
        return commits
