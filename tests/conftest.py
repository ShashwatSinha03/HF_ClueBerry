from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


class FixtureRepo:
    """A tiny local git repository built for a test."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.mkdir(parents=True)
        self._env = {
            "PATH": os.environ.get("PATH", os.defpath),
            "HOME": str(path),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Fixture",
            "GIT_AUTHOR_EMAIL": "fixture@example.com",
            "GIT_COMMITTER_NAME": "Fixture",
            "GIT_COMMITTER_EMAIL": "fixture@example.com",
        }
        self.git("init", "--quiet", "--initial-branch=main")
        # Lets the inspector fetch arbitrary commits by SHA, as GitHub allows.
        self.git("config", "uploadpack.allowAnySHA1InWant", "true")

    @property
    def url(self) -> str:
        return self.path.as_uri()

    def git(self, *args: str) -> str:
        completed = subprocess.run(
            ["git", *args], cwd=self.path, env=self._env, check=True, capture_output=True
        )
        return completed.stdout.decode().strip()

    def write(self, relative: str, content: str | bytes) -> None:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            target.write_text(content)

    def symlink(self, relative: str, points_to: str) -> None:
        target = self.path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(points_to)

    def commit(self, message: str) -> str:
        self.git("add", "--all")
        self.git("commit", "--quiet", "--message", message)
        return self.git("rev-parse", "HEAD")


@pytest.fixture
def make_repo(tmp_path: Path) -> Callable[[str], FixtureRepo]:
    def factory(name: str = "repo") -> FixtureRepo:
        return FixtureRepo(tmp_path / name)

    return factory
