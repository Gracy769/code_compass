"""code_compass.discovery — iterative file-discovery engine."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SKIP_DIRS: frozenset[str] = frozenset(
    {".git", "node_modules", "__pycache__", ".venv", "dist", "build", ".next", "vendor"}
)

_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
}

_BINARY_SNIFF_BYTES = 8192  # 8 KB
_DEFAULT_MAX_FILE_BYTES = 524_288  # 512 KB


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class FileRecord:
    """Metadata for a single discovered file."""

    path: Path
    language: str | None
    size_bytes: int
    is_binary: bool
    too_large: bool = False  # True when size_bytes > max_file_bytes


@dataclass
class RepoManifest:
    """Result of a full repository walk."""

    root: Path
    files: list[FileRecord] = field(default_factory=list)
    skipped_dirs: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_binary(path: Path) -> bool:
    """Return True if *path* appears to be a binary file.

    Reads the first 8 KB and checks for a null byte — the most reliable
    heuristic that requires no external dependency.
    """
    try:
        with path.open("rb") as fh:
            chunk = fh.read(_BINARY_SNIFF_BYTES)
        return b"\x00" in chunk
    except OSError:
        # Unreadable file → treat as binary to skip AST parsing safely.
        return True


def _classify_language(path: Path) -> str | None:
    """Return a language name for *path* based on its extension, or None."""
    return _EXT_TO_LANG.get(path.suffix.lower())


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover(repo_path: Path | str, max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES) -> RepoManifest:
    """Walk *repo_path* and return a :class:`RepoManifest`.

    Uses :func:`os.scandir` for a single-stat-per-entry walk — no full list
    materialisation.  Symlinks are *never* followed: ``entry.is_symlink()`` is
    checked **before** ``entry.is_dir()`` because the latter follows symlinks
    by default.
    """
    root = Path(repo_path).resolve()
    manifest = RepoManifest(root=root)

    # Iterative DFS using an explicit stack instead of recursion.
    stack: list[Path] = [root]

    while stack:
        current_dir = stack.pop()
        try:
            entries = os.scandir(current_dir)
        except PermissionError:
            continue

        with entries:
            for entry in entries:
                # --- Symlink guard (must come before is_dir) ---
                if entry.is_symlink():
                    continue

                if entry.is_dir(follow_symlinks=False):
                    if entry.name in SKIP_DIRS:
                        manifest.skipped_dirs.append(entry.path)
                    else:
                        stack.append(Path(entry.path))
                    continue

                if not entry.is_file(follow_symlinks=False):
                    continue

                stat = entry.stat(follow_symlinks=False)
                size = stat.st_size
                file_path = Path(entry.path)
                lang = _classify_language(file_path)
                # Skip the expensive file-read for known text-only extensions;
                # only sniff files whose extension is not in our language map.
                binary = False if lang is not None else _is_binary(file_path)
                too_large = size > max_file_bytes

                manifest.files.append(
                    FileRecord(
                        path=file_path,
                        language=lang,
                        size_bytes=size,
                        is_binary=binary,
                        too_large=too_large,
                    )
                )

    return manifest
