"""One analysis job per process so the server can enforce a hard deadline."""

from __future__ import annotations

import argparse
import base64
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from code_compass.analysis import analyze
from code_compass.analysis.git_stats import detect_github_slug
from code_compass.discovery import discover
from code_compass.renderer import render
from code_compass.web.security import extract_zip_safely


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("git", "zip"))
    parser.add_argument("source")
    parser.add_argument("work_dir", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--semantic", action="store_true")
    parser.add_argument("--name", default="")
    args = parser.parse_args()
    work_dir: Path = args.work_dir
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
        Repo.clone_from(args.source, repo_dir, depth=1, env=clone_env)
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
        result.repo_stats["contributor_history"] = "shallow clone"
    written = render(result, work_dir / "dashboard.html", repo_name=repo_name, github_slug=slug, github_ref=repo_ref)
    written.chmod(0o600)
    written.with_name("dashboard-summary.html").chmod(0o600)


if __name__ == "__main__":
    main()
