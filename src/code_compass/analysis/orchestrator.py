"""code_compass.analysis.orchestrator — top-level analysis coordinator."""

from __future__ import annotations

from code_compass.analysis.dead_code import find_dead_code
from code_compass.analysis.git_stats import collect_git_stats
from code_compass.analysis.js_analyzer import analyze_js
from code_compass.analysis.models import AnalysisResult
from code_compass.analysis.python_analyzer import analyze_python
from code_compass.analysis.semantic_auditor import run_semantic_audit
from code_compass.discovery import RepoManifest


def analyze(manifest: RepoManifest, strict: bool = False, semantic: bool = False) -> AnalysisResult:
    """Analyse all files in *manifest* and return an :class:`AnalysisResult`.

    * Python files are parsed with stdlib :mod:`ast`.
    * JavaScript / TypeScript files are parsed with ``tree-sitter``.
    * Files marked ``too_large=True`` or ``is_binary=True`` are silently skipped.
    * Any parse exception is caught; the file path + error message is appended
      to :attr:`AnalysisResult.parse_errors` and execution continues.
    * The dead-code pass runs only when *strict* is ``True``.
    * Git contributor stats are collected unconditionally.
    * The semantic-audit pass runs only when *semantic* is ``True``. It selects
      the top-5 most complex files and runs ``run_semantic_audit``.
    """
    result = AnalysisResult()

    for record in manifest.files:
        # Skip files that should not be parsed.
        if record.is_binary or record.too_large:
            continue
        if record.language not in ("python", "javascript", "typescript"):
            continue

        try:
            if record.language == "python":
                symbols, edges = analyze_python(record.path)
            else:
                symbols, edges = analyze_js(record.path, record.language)
        except Exception as exc:  # noqa: BLE001
            result.parse_errors.append(f"{record.path}: {exc}")
            continue

        result.symbols.extend(symbols)
        result.call_edges.extend(edges)

    if strict:
        result.dead_code = find_dead_code(result)

    result.contributors = collect_git_stats(manifest.root)

    if semantic:
        result.semantic_findings = run_semantic_audit(result, manifest.root)

    return result
