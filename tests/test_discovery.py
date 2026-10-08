"""tests/test_discovery.py — ST-8 edge-case and performance tests for the discovery engine."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from code_compass.discovery import discover


# ---------------------------------------------------------------------------
# test_skips_dotgit
# ---------------------------------------------------------------------------


def test_skips_dotgit(tmp_repo: Path) -> None:
    """.git/ directory must not appear in the manifest file list."""
    git_dir = tmp_repo / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("[core]\n    bare = false\n", encoding="utf-8")
    # Also add a normal Python file so the manifest is non-trivially populated.
    (tmp_repo / "main.py").write_text("x = 1\n", encoding="utf-8")

    manifest = discover(tmp_repo)

    paths = [r.path for r in manifest.files]
    assert not any(".git" in p.parts for p in paths), (
        f".git contents found in manifest: {[p for p in paths if '.git' in p.parts]}"
    )


# ---------------------------------------------------------------------------
# test_skips_node_modules
# ---------------------------------------------------------------------------


def test_skips_node_modules(tmp_repo: Path) -> None:
    """node_modules/ must not be traversed."""
    nm = tmp_repo / "node_modules"
    nm.mkdir()
    (nm / "lodash.js").write_text("module.exports = {};\n", encoding="utf-8")
    (tmp_repo / "index.js").write_text("const x = 1;\n", encoding="utf-8")

    manifest = discover(tmp_repo)

    paths = [r.path for r in manifest.files]
    assert not any("node_modules" in p.parts for p in paths), (
        f"node_modules contents found in manifest: {[p for p in paths if 'node_modules' in p.parts]}"
    )


# ---------------------------------------------------------------------------
# test_excludes_symlinks
# ---------------------------------------------------------------------------


def test_excludes_symlinks(tmp_repo: Path) -> None:
    """Symlinked files and directories must be silently skipped.

    Uses os.symlink — skipped on Windows when symlink creation requires elevation
    (OSError / NotImplementedError).
    """
    real_file = tmp_repo / "real.py"
    real_file.write_text("x = 1\n", encoding="utf-8")

    link_file = tmp_repo / "link.py"
    try:
        os.symlink(real_file, link_file)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation requires elevated privileges on this platform")

    manifest = discover(tmp_repo)

    paths = [r.path for r in manifest.files]
    assert link_file.resolve() not in [p.resolve() for p in paths], (
        "Symlinked file was included in the manifest"
    )
    # The real file should still appear.
    assert any(p.name == "real.py" for p in paths), "real.py missing from manifest"


# ---------------------------------------------------------------------------
# test_binary_detection
# ---------------------------------------------------------------------------


def test_binary_detection(tmp_repo: Path) -> None:
    """A file that contains a null byte must be classified as binary."""
    bin_file = tmp_repo / "data.bin"
    bin_file.write_bytes(b"PNG\x00\x00\x00\x89some binary content")

    manifest = discover(tmp_repo)

    records = {r.path.name: r for r in manifest.files}
    assert "data.bin" in records, "Binary file not found in manifest"
    assert records["data.bin"].is_binary is True, (
        f"Expected is_binary=True, got {records['data.bin'].is_binary}"
    )


# ---------------------------------------------------------------------------
# test_large_file_excluded
# ---------------------------------------------------------------------------


def test_large_file_excluded(tmp_repo: Path) -> None:
    """A file exceeding 512 KB is present in the manifest but marked too_large=True."""
    big_file = tmp_repo / "huge.py"
    # Write 513 KB of Python-ish content (no null bytes -> not binary).
    big_file.write_bytes(b"# padding\n" * 52_429)  # ~524 KB

    manifest = discover(tmp_repo)

    records = {r.path.name: r for r in manifest.files}
    assert "huge.py" in records, "Large file not found in manifest at all"
    assert records["huge.py"].too_large is True, (
        f"Expected too_large=True, got {records['huge.py'].too_large}"
    )


# ---------------------------------------------------------------------------
# test_empty_repo
# ---------------------------------------------------------------------------


def test_empty_repo(tmp_repo: Path) -> None:
    """An empty directory must return a manifest with zero files — no crash."""
    manifest = discover(tmp_repo)

    assert manifest.files == [], (
        f"Expected empty file list for empty repo, got {manifest.files}"
    )


# ---------------------------------------------------------------------------
# test_10k_files_performance
# ---------------------------------------------------------------------------


def test_10k_files_performance(tmp_repo: Path) -> None:
    """Discovery of 10 000 Python stubs must complete in under 2 seconds."""
    stub_dir = tmp_repo / "stubs"
    stub_dir.mkdir()
    for i in range(10_000):
        (stub_dir / f"mod_{i:05d}.py").write_text(
            f"def func_{i}(): pass\n", encoding="utf-8"
        )

    start = time.perf_counter()
    manifest = discover(tmp_repo)
    elapsed = time.perf_counter() - start

    assert len(manifest.files) == 10_000, (
        f"Expected 10 000 files, got {len(manifest.files)}"
    )
    assert elapsed < 2.0, (
        f"Discovery took {elapsed:.3f}s — expected <2s on 10k files"
    )
