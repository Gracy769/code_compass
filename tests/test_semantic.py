"""tests/test_semantic.py — Phase 1 hybrid engine tests for semantic audit."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_compass.analysis.models import AnalysisResult, SemanticFinding
from code_compass.analysis.orchestrator import analyze
from code_compass.discovery import FileRecord, RepoManifest
from code_compass.renderer import render


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_SEVERITIES = {"high", "medium", "low"}
_VALID_CATEGORIES = {"race_condition", "state_mutation", "error_handling", "insecure_defaults"}


def _write_py(tmp_repo: Path, name: str, source: str) -> Path:
    """Write *source* to *tmp_repo/<name>* and return the path."""
    p = tmp_repo / name
    p.write_text(source, encoding="utf-8")
    return p


def _manifest_for(tmp_repo: Path, files: list[FileRecord]) -> RepoManifest:
    return RepoManifest(root=tmp_repo, files=files)


def _record(p: Path) -> FileRecord:
    """Build a FileRecord for a Python source file at *p*."""
    return FileRecord(path=p, language="python", size_bytes=p.stat().st_size, is_binary=False)


# ---------------------------------------------------------------------------
# test_top5_selection
# ---------------------------------------------------------------------------


def test_top5_selection(tmp_repo: Path) -> None:
    """Only the top-5 most complex files are audited — 5 × 3 = 15 findings total."""
    # 7 files with distinct McCabe complexities (1 base + N branches).
    # Complexities: 8, 7, 6, 5, 4, 3, 2 → top-5 are the first five.
    sources = [
        # complexity 8 (1 + 7 ifs)
        (
            "f0.py",
            "def func(a,b,c,d,e,f,g):\n"
            "    if a: pass\n"
            "    if b: pass\n"
            "    if c: pass\n"
            "    if d: pass\n"
            "    if e: pass\n"
            "    if f: pass\n"
            "    if g: pass\n"
            "    return a\n",
        ),
        # complexity 7 (1 + 6 ifs)
        (
            "f1.py",
            "def func(a,b,c,d,e,f):\n"
            "    if a: pass\n"
            "    if b: pass\n"
            "    if c: pass\n"
            "    if d: pass\n"
            "    if e: pass\n"
            "    if f: pass\n"
            "    return a\n",
        ),
        # complexity 6 (1 + 5 ifs)
        (
            "f2.py",
            "def func(a,b,c,d,e):\n"
            "    if a: pass\n"
            "    if b: pass\n"
            "    if c: pass\n"
            "    if d: pass\n"
            "    if e: pass\n"
            "    return a\n",
        ),
        # complexity 5 (1 + 4 ifs)
        (
            "f3.py",
            "def func(a,b,c,d):\n"
            "    if a: pass\n"
            "    if b: pass\n"
            "    if c: pass\n"
            "    if d: pass\n"
            "    return a\n",
        ),
        # complexity 4 (1 + 3 ifs)
        (
            "f4.py",
            "def func(a,b,c):\n"
            "    if a: pass\n"
            "    if b: pass\n"
            "    if c: pass\n"
            "    return a\n",
        ),
        # complexity 3 (1 + 2 ifs) — should be excluded from top-5
        (
            "f5.py",
            "def func(a,b):\n"
            "    if a: pass\n"
            "    if b: pass\n"
            "    return a\n",
        ),
        # complexity 2 (1 + 1 if) — should be excluded from top-5
        (
            "f6.py",
            "def func(a):\n"
            "    if a: pass\n"
            "    return a\n",
        ),
    ]

    records = []
    for name, src in sources:
        p = _write_py(tmp_repo, name, src)
        records.append(_record(p))

    manifest = _manifest_for(tmp_repo, records)
    result = analyze(manifest, semantic=True)

    assert len(result.semantic_findings) == 15, (
        f"Expected 15 findings (5 files × 3 each), got {len(result.semantic_findings)}"
    )
    for finding in result.semantic_findings:
        assert isinstance(finding, SemanticFinding), (
            f"Expected SemanticFinding instance, got {type(finding)!r}"
        )


# ---------------------------------------------------------------------------
# test_fewer_than_5_files
# ---------------------------------------------------------------------------


def test_fewer_than_5_files(tmp_repo: Path) -> None:
    """With only 2 Python files the auditor processes both — 2 × 3 = 6 findings."""
    sources = [
        ("a.py", "def alpha():\n    return 1\n"),
        ("b.py", "def beta():\n    return 2\n"),
    ]

    records = []
    for name, src in sources:
        p = _write_py(tmp_repo, name, src)
        records.append(_record(p))

    manifest = _manifest_for(tmp_repo, records)
    result = analyze(manifest, semantic=True)

    assert len(result.semantic_findings) == 6, (
        f"Expected 6 findings (2 files × 3 each), got {len(result.semantic_findings)}"
    )


# ---------------------------------------------------------------------------
# test_finding_structure
# ---------------------------------------------------------------------------


def test_finding_structure(tmp_repo: Path) -> None:
    """Every SemanticFinding must have valid, non-empty field values."""
    src = (
        "def complex_fn(a, b, c):\n"
        "    if a:\n"
        "        pass\n"
        "    if b:\n"
        "        pass\n"
        "    if c:\n"
        "        pass\n"
        "    return a\n"
    )
    p = _write_py(tmp_repo, "structured.py", src)
    manifest = _manifest_for(tmp_repo, [_record(p)])
    result = analyze(manifest, semantic=True)

    assert result.semantic_findings, "Expected at least one SemanticFinding"

    for finding in result.semantic_findings:
        assert finding.file, (
            f"finding.file must be a non-empty string, got {finding.file!r}"
        )
        assert finding.severity in _VALID_SEVERITIES, (
            f"finding.severity {finding.severity!r} is not one of {_VALID_SEVERITIES}"
        )
        assert finding.category in _VALID_CATEGORIES, (
            f"finding.category {finding.category!r} is not one of {_VALID_CATEGORIES}"
        )
        assert finding.summary, (
            f"finding.summary must be a non-empty string, got {finding.summary!r}"
        )
        assert finding.detail, (
            f"finding.detail must be a non-empty string, got {finding.detail!r}"
        )
        assert finding.prompt_used, (
            f"finding.prompt_used must be a non-empty string, got {finding.prompt_used!r}"
        )
        assert finding.prompt_used != "[mock]", (
            "finding.prompt_used must contain the real prompt, not the '[mock]' sentinel"
        )


# ---------------------------------------------------------------------------
# test_prompt_contains_source
# ---------------------------------------------------------------------------


def test_prompt_contains_source(tmp_repo: Path) -> None:
    """_build_prompt must embed the file's source — the unique function name appears in prompt_used."""
    src = (
        "def super_unique_function_xyz():\n"
        "    x = 1\n"
        "    if x:\n"
        "        pass\n"
        "    if not x:\n"
        "        pass\n"
        "    return x\n"
    )
    p = _write_py(tmp_repo, "unique.py", src)
    manifest = _manifest_for(tmp_repo, [_record(p)])
    result = analyze(manifest, semantic=True)

    assert result.semantic_findings, "Expected at least one SemanticFinding from unique.py"

    prompts_with_name = [
        f for f in result.semantic_findings
        if "super_unique_function_xyz" in f.prompt_used
    ]
    assert prompts_with_name, (
        "Expected at least one finding whose prompt_used contains 'super_unique_function_xyz'; "
        f"prompts were: {[f.prompt_used[:120] for f in result.semantic_findings]}"
    )


# ---------------------------------------------------------------------------
# test_orchestrator_semantic_flag
# ---------------------------------------------------------------------------


def test_orchestrator_semantic_flag(tmp_repo: Path) -> None:
    """semantic=False must produce no findings; semantic=True must produce findings."""
    sources = [
        ("x.py", "def foo(a, b):\n    if a: pass\n    if b: pass\n    return a\n"),
        ("y.py", "def bar(c, d):\n    if c: pass\n    if d: pass\n    return c\n"),
    ]
    records = []
    for name, src in sources:
        p = _write_py(tmp_repo, name, src)
        records.append(_record(p))

    manifest = _manifest_for(tmp_repo, records)

    result_off = analyze(manifest, semantic=False)
    assert result_off.semantic_findings == [], (
        f"Expected no semantic findings with semantic=False, got {result_off.semantic_findings}"
    )

    result_on = analyze(manifest, semantic=True)
    assert len(result_on.semantic_findings) > 0, (
        "Expected semantic findings with semantic=True, got none"
    )


# ---------------------------------------------------------------------------
# test_renderer_includes_findings
# ---------------------------------------------------------------------------


def test_renderer_includes_findings(tmp_repo: Path) -> None:
    """The rendered HTML must embed semantic_findings JSON and the first finding's summary."""
    src = (
        "def risky(a, b, c):\n"
        "    if a: pass\n"
        "    if b: pass\n"
        "    if c: pass\n"
        "    return a\n"
    )
    p = _write_py(tmp_repo, "risky.py", src)
    manifest = _manifest_for(tmp_repo, [_record(p)])
    result = analyze(manifest, semantic=True)

    assert result.semantic_findings, "Expected findings before rendering"

    output = tmp_repo / "out.html"
    render(result, output, repo_name="test-repo")

    html = output.read_text(encoding="utf-8")

    assert "semantic_findings" in html, (
        "Expected 'semantic_findings' key to appear in the rendered HTML JSON block"
    )

    first_summary = result.semantic_findings[0].summary
    assert first_summary in html, (
        f"Expected the first finding summary {first_summary!r} to appear in the rendered HTML"
    )
