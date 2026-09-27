"""One analysis job per process so the server can enforce a hard deadline."""

from __future__ import annotations

import argparse
import base64
import dataclasses
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from code_compass.analysis import analyze
from code_compass.analysis.git_stats import detect_github_slug
from code_compass.analysis.models import AnalysisResult, CallEdge, ContributorStat, FileMetadata, SemanticFinding, SymbolInfo
from code_compass.analysis.semantic_auditor import audit_with_provider
from code_compass.analysis.tagger import generate_ai_system_prompt
from code_compass.discovery import discover
from code_compass.renderer import render
from code_compass.web.security import extract_zip_safely


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("git", "zip", "audit"))
    parser.add_argument("source")
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--name", default="")
    parser.add_argument("--endpoint", default="")
    parser.add_argument("--model", default="")
    args = parser.parse_args()
    work_dir: Path = args.work_dir
    if args.kind == "audit":
        data = json.loads((work_dir / "analysis.json").read_text(encoding="utf-8"))
        meta = json.loads((work_dir / "analysis-meta.json").read_text(encoding="utf-8"))
        result = AnalysisResult(
            symbols=[SymbolInfo(**x) for x in data["symbols"]],
            call_edges=[CallEdge(**x) for x in data["call_edges"]],
            contributors=[ContributorStat(**x) for x in data["contributors"]],
            parse_errors=data["parse_errors"], dead_code=data["dead_code"],
            semantic_findings=[SemanticFinding(**x) for x in data["semantic_findings"]],
            files=[FileMetadata(**x) for x in data["files"]],
            architecture_mermaid=data["architecture_mermaid"],
            ai_system_prompt=data["ai_system_prompt"], repo_stats=data["repo_stats"],
        )
        target = (work_dir / meta["target"]).resolve()
        if not target.is_relative_to(work_dir.resolve()):
            raise ValueError("Invalid analysis source path")
        key = os.environ.pop("CODE_COMPASS_AUDIT_KEY", "")
        result.semantic_findings = audit_with_provider(
            result, target, endpoint=args.endpoint, model=args.model, api_key=key,
        )
        result.repo_stats["semantic_status"] = "available"
        result.repo_stats["semantic_scope"] = "up to 12 ranked files"
        result.repo_stats["semantic_model"] = args.model
        result.ai_system_prompt = generate_ai_system_prompt(
            repo_name=meta["render"]["repo_name"], total_files=len(result.files),
            symbols=[{"name": s.name, "file": s.file} for s in result.symbols],
            ranked_files=[dataclasses.asdict(f) for f in sorted(result.files, key=lambda f: f.rank_score, reverse=True)],
            contributors=[{"author": c.author, "commits": c.commits} for c in result.contributors],
            semantic_findings=[dataclasses.asdict(f) for f in result.semantic_findings],
            semantic_status="available",
        )
        temp = render(result, work_dir / "dashboard.next.html", **meta["render"])
        temp.write_text(
            temp.read_text(encoding="utf-8").replace("dashboard.next-summary.html", "dashboard-summary.html"),
            encoding="utf-8",
        )
        temp.replace(work_dir / "dashboard.html")
        temp.with_name("dashboard.next-summary.html").replace(work_dir / "dashboard-summary.html")
        (work_dir / "analysis.json").write_text(json.dumps(dataclasses.asdict(result)), encoding="utf-8")
        return
    repo_dir = work_dir / "repo"
    repo_dir.mkdir(parents=True, exist_ok=True)

    if args.kind == "git":
        from git import Repo

        clone_env = os.environ.copy()
        token = clone_env.pop("CODE_COMPASS_CLONE_TOKEN", "")
        if token:
            credential = base64.b64encode(f"x-access-token:{token}".encode()).decode()
            clone_env.update({
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": "http.https://github.com/.extraheader",
                "GIT_CONFIG_VALUE_0": f"AUTHORIZATION: basic {credential}",
            })
        # Keep the full commit graph for an accurate fallback when GitHub's
        # contributor API is unavailable; blob filtering reduces transfer.
        Repo.clone_from(args.source, repo_dir, multi_options=["--filter=blob:none"], env=clone_env)
        target = repo_dir
        slug = detect_github_slug(repo_dir)
        repo_ref = Repo(repo_dir).head.commit.hexsha
        repo_name = Path(urlsplit(args.source).path).stem
    else:
        extract_zip_safely(Path(args.source), repo_dir)
        candidates = [p for p in repo_dir.iterdir() if p.is_dir() and not p.name.startswith(".")]
        target = candidates[0] if len(candidates) == 1 else repo_dir
        slug = ""
        repo_ref = ""
        repo_name = args.name or target.name

    started = time.perf_counter()
    manifest = discover(target)
    result = analyze(manifest, strict=args.strict, semantic=args.semantic)
    result.repo_stats["analysis_seconds"] = round(time.perf_counter() - started, 2)
    if args.kind == "git":
        result.repo_stats["contributor_history"] = (
            "GitHub API" if result.contributors and result.contributors[0].github_handle
            else "full git history"
        )
    render_args = {"repo_name": repo_name, "github_slug": slug, "github_ref": repo_ref}
    (work_dir / "analysis-meta.json").write_text(json.dumps({
        "target": str(target.relative_to(work_dir)), "render": render_args,
    }), encoding="utf-8")
    (work_dir / "analysis.json").write_text(json.dumps(dataclasses.asdict(result)), encoding="utf-8")
    written = render(result, work_dir / "dashboard.html", **render_args)
    written.chmod(0o600)
    written.with_name("dashboard-summary.html").chmod(0o600)


if __name__ == "__main__":
    main()
