from __future__ import annotations

from typing import Literal

from .git import TreeEntry

SnippetCategory = Literal["source", "documentation", "test"]

_REGULAR_FILE_MODES = frozenset({"100644", "100755"})

EXCLUDED_DIRECTORIES = frozenset(
    {
        "node_modules",
        "bower_components",
        "vendor",
        "third_party",
        "dist",
        "build",
        "target",
        "out",
        "__pycache__",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".next",
        "coverage",
        "site-packages",
        "pods",
    }
)

GENERATED_FILENAMES = frozenset(
    {
        "package-lock.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "poetry.lock",
        "pipfile.lock",
        "uv.lock",
        "cargo.lock",
        "composer.lock",
        "gemfile.lock",
        "go.sum",
    }
)

GENERATED_SUFFIXES = (
    ".min.js",
    ".min.css",
    ".map",
    ".lock",
    "_pb2.py",
    "_pb2_grpc.py",
    ".pb.go",
)

BINARY_SUFFIXES = frozenset(
    {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".webp", ".svgz", ".tiff",
        ".pdf", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".tar", ".rar", ".jar",
        ".war", ".whl", ".egg", ".so", ".dylib", ".dll", ".exe", ".bin", ".o", ".a",
        ".class", ".pyc", ".pyo", ".wasm", ".woff", ".woff2", ".ttf", ".otf", ".eot",
        ".mp3", ".mp4", ".mov", ".avi", ".wav", ".flac", ".ogg", ".webm",
        ".sqlite", ".db", ".parquet", ".npy", ".pkl",
    }
)  # fmt: skip

_DOC_SUFFIXES = (".md", ".rst", ".txt", ".adoc")
_DOC_DIRECTORIES = frozenset({"docs", "doc", "documentation"})
_DOC_NAME_PREFIXES = ("readme", "changelog", "contributing", "history", "news", "faq")
_TEST_DIRECTORIES = frozenset({"test", "tests", "spec", "specs", "__tests__", "testing"})


def _suffix(name: str) -> str:
    dot = name.rfind(".")
    return name[dot:] if dot > 0 else ""


def skip_reason(entry: TreeEntry, max_file_bytes: int) -> str | None:
    """Return why a tree entry is excluded from inspection, or None if it's eligible."""
    if entry.mode == "120000":
        return "symlink"
    if entry.mode == "160000" or entry.object_type == "commit":
        return "submodule"
    if entry.object_type != "blob" or entry.mode not in _REGULAR_FILE_MODES:
        return "unsupported_mode"
    segments = entry.path.split("/")
    if (
        "�" in entry.path
        or any(ord(ch) < 32 for ch in entry.path)
        or any(segment in ("", ".", "..") for segment in segments)
    ):
        return "invalid_path"  # includes malformed trees with "..", "." or empty names

    if any(segment.lower() in EXCLUDED_DIRECTORIES for segment in segments[:-1]):
        return "excluded_directory"

    name = segments[-1].lower()
    if name in GENERATED_FILENAMES or name.endswith(GENERATED_SUFFIXES):
        return "generated"
    if _suffix(name) in BINARY_SUFFIXES:
        return "binary"
    if entry.size is None or entry.size > max_file_bytes:
        return "oversized"
    return None


def categorize(path: str) -> SnippetCategory:
    segments = path.lower().split("/")
    name = segments[-1]
    directories = segments[:-1]

    if (
        any(d in _TEST_DIRECTORIES for d in directories)
        or name.startswith("test_")
        or name.removesuffix(_suffix(name)).endswith(("_test", "_spec", "-test", "-spec"))
        or ".test." in name
        or ".spec." in name
    ):
        return "test"
    if (
        name.endswith(_DOC_SUFFIXES)
        or any(d in _DOC_DIRECTORIES for d in directories)
        or name.startswith(_DOC_NAME_PREFIXES)
    ):
        return "documentation"
    return "source"


def decode_text(content: bytes) -> str | None:
    """Decode file content as UTF-8 text, or return None if it looks binary."""
    if b"\x00" in content[:8192]:
        return None
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return None


def split_lines(text: str) -> list[str]:
    """Split on newlines only, matching how GitHub and editors number lines."""
    lines = [line.removesuffix("\r") for line in text.split("\n")]
    if lines and lines[-1] == "":
        lines.pop()
    return lines
