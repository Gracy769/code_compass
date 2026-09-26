"""tests/test_analysis.py — ST-8 correctness tests for the AST analysis engine."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_compass.analysis.models import AnalysisResult, SymbolInfo, CallEdge
from code_compass.analysis.python_analyzer import analyze_python
from code_compass.analysis.dead_code import find_dead_code
from code_compass.analysis.orchestrator import analyze
from code_compass.discovery import FileRecord, RepoManifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_py(tmp_repo: Path, name: str, source: str) -> Path:
    """Write *source* to *tmp_repo/<name>* and return the path."""
    p = tmp_repo / name
    p.write_text(source, encoding="utf-8")
    return p


def _manifest_for(tmp_repo: Path, files: list[FileRecord]) -> RepoManifest:
    return RepoManifest(root=tmp_repo, files=files)


# ---------------------------------------------------------------------------
# test_python_complexity_simple
# ---------------------------------------------------------------------------


def test_python_complexity_simple(tmp_repo: Path) -> None:
    """A function with no branches must have cyclomatic complexity = 1."""
    src = "def simple():\n    return 42\n"
    p = _write_py(tmp_repo, "simple.py", src)

    symbols, _ = analyze_python(p)

    fn = next((s for s in symbols if s.name == "simple"), None)
    assert fn is not None, "Function 'simple' not found in symbols"
    assert fn.complexity == 1, (
        f"Expected complexity 1 for branch-free function, got {fn.complexity}"
    )


# ---------------------------------------------------------------------------
# test_python_complexity_branching
# ---------------------------------------------------------------------------


def test_python_complexity_branching(tmp_repo: Path) -> None:
    """A function with 3 `if` statements must have cyclomatic complexity = 4."""
    src = (
        "def branchy(x, y, z):\n"
        "    if x:\n"
        "        pass\n"
        "    if y:\n"
        "        pass\n"
        "    if z:\n"
        "        pass\n"
        "    return x\n"
    )
    p = _write_py(tmp_repo, "branchy.py", src)

    symbols, _ = analyze_python(p)

    fn = next((s for s in symbols if s.name == "branchy"), None)
    assert fn is not None, "Function 'branchy' not found in symbols"
    assert fn.complexity == 4, (
        f"Expected complexity 4 (1 base + 3 branches), got {fn.complexity}"
    )


# ---------------------------------------------------------------------------
# test_dead_code_detection
# ---------------------------------------------------------------------------


def test_dead_code_detection(tmp_repo: Path) -> None:
    """A function defined but never called must appear in the dead code list."""
    src = (
        "def used():\n"
        "    pass\n"
        "\n"
        "def orphan():\n"
        "    pass\n"
        "\n"
        "def caller():\n"
        "    used()\n"
    )
    p = _write_py(tmp_repo, "dead.py", src)

    symbols, edges = analyze_python(p)

    result = AnalysisResult(symbols=symbols, call_edges=edges)
    dead = find_dead_code(result)

    assert "orphan" in dead, (
        f"Expected 'orphan' in dead code list, got {dead}"
    )
    # 'used' is called by 'caller', so it should NOT be flagged.
    assert "used" not in dead, (
        f"'used' should not be in dead code list, got {dead}"
    )


# ---------------------------------------------------------------------------
# test_parse_error_graceful
# ---------------------------------------------------------------------------


def test_parse_error_graceful(tmp_repo: Path) -> None:
    """A file with a syntax error must be skipped — not a crash.

    The orchestrator records the file in parse_errors and continues.
    """
    bad = _write_py(tmp_repo, "broken.py", "def oops(\n    # unclosed paren\n")
    good = _write_py(tmp_repo, "ok.py", "def fine(): pass\n")

    records = [
        FileRecord(path=bad,  language="python", size_bytes=bad.stat().st_size,  is_binary=False),
        FileRecord(path=good, language="python", size_bytes=good.stat().st_size, is_binary=False),
    ]
    manifest = _manifest_for(tmp_repo, records)

    # analyze() must not raise; broken.py ends up in parse_errors.
    result = analyze(manifest, strict=False)

    assert any("broken.py" in e for e in result.parse_errors), (
        f"Expected broken.py in parse_errors, got {result.parse_errors}"
    )
    # The good file still yields symbols.
    assert any(s.name == "fine" for s in result.symbols), (
        "Expected 'fine' function from ok.py in symbols"
    )


# ---------------------------------------------------------------------------
# test_binary_blob_skipped
# ---------------------------------------------------------------------------


def test_binary_blob_skipped(tmp_repo: Path) -> None:
    """A .py file containing binary content must not crash the analyzer.

    The orchestrator skips files whose FileRecord has is_binary=True, so no
    exception should propagate and no symbol should appear from that file.
    """
    binary_py = tmp_repo / "blob.py"
    binary_py.write_bytes(b"\x00\x01\x02ELF binary content\x00\x00")

    record = FileRecord(
        path=binary_py,
        language="python",
        size_bytes=binary_py.stat().st_size,
        is_binary=True,  # orchestrator must skip this
    )
    manifest = _manifest_for(tmp_repo, [record])

    # Must not raise.
    result = analyze(manifest, strict=False)

    blob_str = str(binary_py)
    assert not any(s.file == blob_str for s in result.symbols), (
        "Symbols were extracted from a binary-flagged file"
    )
    assert result.parse_errors == [], (
        f"Unexpected parse errors for skipped binary file: {result.parse_errors}"
    )
