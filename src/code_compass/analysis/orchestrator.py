"""code_compass.analysis.orchestrator — top-level analysis coordinator."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from code_compass.analysis.dead_code import find_dead_code
from code_compass.analysis.git_stats import collect_git_stats
from code_compass.analysis.js_analyzer import analyze_js
from code_compass.analysis.models import AnalysisResult, FileMetadata
from code_compass.analysis.python_analyzer import analyze_python
from code_compass.analysis.semantic_auditor import run_semantic_audit
from code_compass.analysis.tagger import (
    classify_layer,
    compute_file_rankings,
    extract_tags,
    generate_ai_system_prompt,
    generate_mermaid_architecture,
)
from code_compass.discovery import RepoManifest


def analyze(manifest: RepoManifest, strict: bool = False, semantic: bool = True) -> AnalysisResult:
    """Analyse all files in *manifest* and return an :class:`AnalysisResult`."""
    result = AnalysisResult()
    file_sym_map: dict[str, list[str]] = defaultdict(list)
    file_complexity_map: dict[str, int] = defaultdict(int)

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

        rel_path = str(record.path)
        try:
            rel_path = str(record.path.relative_to(manifest.root))
        except ValueError:
            pass

        # Tag each symbol and assign layer
        for s in symbols:
            s_layer = classify_layer(s.file, [s.name])
            s_tags = extract_tags(s.file, symbol_names=[s.name])
            s.layer = s_layer
            s.tags = s_tags
            file_sym_map[s.file].append(s.name)
            file_complexity_map[s.file] = max(file_complexity_map[s.file], s.complexity)

        result.symbols.extend(symbols)
        result.call_edges.extend(edges)

    if strict:
        result.dead_code = find_dead_code(result)

    result.contributors = collect_git_stats(manifest.root)

    # Compile raw file list for ranking
    raw_files = []
    seen_paths = set()
    for record in manifest.files:
        if record.is_binary or record.too_large:
            continue
        rel = str(record.path)
        try:
            rel = str(record.path.relative_to(manifest.root))
        except ValueError:
            pass
        if rel in seen_paths:
            continue
        seen_paths.add(rel)

        sym_names = file_sym_map.get(rel, []) or file_sym_map.get(str(record.path), [])
        max_comp = file_complexity_map.get(rel, 1) or file_complexity_map.get(str(record.path), 1)

        raw_files.append({
            "path": rel,
            "language": record.language or "unknown",
            "size": record.size_bytes,
            "complexity": max_comp,
            "symbols_count": len(sym_names),
        })

    # Rank files & assign 10 structural layers + tiers
    ranked = compute_file_rankings(raw_files, result.symbols, result.call_edges)
    result.files = [
        FileMetadata(
            path=r["path"],
            language=r["language"],
            size=r["size"],
            complexity=r["complexity"],
            symbols_count=r["symbols_count"],
            layer=r["layer"],
            ranking_tier=r["ranking_tier"],
            rank_score=r["rank_score"],
            in_degree=r["in_degree"],
            out_degree=r["out_degree"],
            tags=r["tags"],
            rank=r.get("rank", 1),
        )
        for r in ranked
    ]

    # Generate interactive Mermaid architecture
    repo_name = manifest.root.name
    result.architecture_mermaid = generate_mermaid_architecture(ranked, result.call_edges, repo_name=repo_name)

    # Run semantic audit if requested
    if semantic:
        result.semantic_findings = run_semantic_audit(result, manifest.root)

    # Generate exhaustive AI System Prompt for overview / AI synthesis
    result.ai_system_prompt = generate_ai_system_prompt(
        repo_name=repo_name,
        total_files=len(result.files),
        symbols=[{"name": s.name, "file": s.file} for s in result.symbols],
        ranked_files=ranked,
        contributors=[{"author": c.author, "commits": c.commits} for c in result.contributors],
        semantic_findings=[{"severity": f.severity, "category": f.category, "summary": f.summary, "file": f.file} for f in result.semantic_findings],
    )

    # Health score metrics
    total_syms = len(result.symbols) or 1
    dead_ratio = round((len(result.dead_code) / total_syms) * 100, 1)
    health_score = max(50, min(100, int(100 - (dead_ratio * 1.5) - (len(result.parse_errors) * 2))))
    result.repo_stats = {
        "health_score": health_score,
        "total_files": len(result.files),
        "total_symbols": len(result.symbols),
        "total_edges": len(result.call_edges),
        "total_contributors": len(result.contributors),
        "dead_code_count": len(result.dead_code),
        "dead_code_ratio": dead_ratio,
    }

    return result
