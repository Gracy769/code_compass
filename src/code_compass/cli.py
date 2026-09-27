"""code_compass.cli — entry point for the `code-compass` command."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from code_compass.analysis import analyze as run_analysis
from code_compass.analysis.git_stats import detect_github_slug
from code_compass.discovery import discover
from code_compass.renderer import render
from code_compass.cache_manager import compute_hash, load_cache, save_cache


@click.group()
def main() -> None:
    """Code Compass — static analysis dashboard for Git repositories."""


@main.command()
@click.argument("repo_path", type=click.Path(exists=True, file_okay=False, resolve_path=True))
@click.option(
    "--output",
    default="compass-dashboard.html",
    show_default=True,
    help="Path to write the HTML dashboard.",
)
@click.option(
    "--strict",
    is_flag=True,
    default=False,
    help="Enable dead-code detection (opt-in; may produce false positives on public APIs).",
)
@click.option(
    "--semantic",
    is_flag=True,
    default=False,
    help="Reserved for a future semantic audit provider; no findings are generated yet.",
)
def analyze(repo_path: str, output: str, strict: bool, semantic: bool) -> None:
    """Analyse REPO_PATH and emit a self-contained HTML dashboard."""
    repo = Path(repo_path)
    out = Path(output)

    click.echo(f"[code-compass] Analysing repository: {repo}")
    click.echo(f"[code-compass] Output: {out}")
    if strict:
        click.echo("[code-compass] Dead-code detection: enabled")
    if semantic:
        click.echo("[code-compass] Semantic audit is not configured; no semantic findings will be generated.")

    from git import Repo
    try:
        repo_ref = Repo(repo, search_parent_directories=False).head.commit.hexsha
    except Exception:
        repo_ref = ""

    hash_str = compute_hash(str(repo), repo_ref)
    cached = load_cache(hash_str, ttl_days=30)

    if cached is not None:
        click.echo("[code-compass] Loaded analysis from Supabase cache!")
        result = cached
    else:
        manifest = discover(repo)
        total = len(manifest.files)
        parseable = sum(1 for f in manifest.files if not f.is_binary and not f.too_large)
        click.echo(
            f"[code-compass] Discovered {total} file(s) "
            f"({parseable} parseable, {total - parseable} skipped)."
        )

        click.echo("[code-compass] Analysing symbols…")
        result = run_analysis(manifest, strict=strict, semantic=semantic, prefer_local_contributors=True)

        sym_count = len(result.symbols)
        edge_count = len(result.call_edges)
        contrib_count = len(result.contributors)
        click.echo(
            f"[code-compass] Found {sym_count} symbol(s), "
            f"{edge_count} call edge(s), "
            f"{contrib_count} contributor(s)."
        )
        if result.parse_errors:
            click.echo(
                f"[code-compass] {len(result.parse_errors)} file(s) skipped due to parse errors.",
                err=True,
            )
        if strict and result.dead_code:
            click.echo(
                f"[code-compass] Dead code candidates: {len(result.dead_code)} symbol(s)."
            )
        if semantic and result.semantic_findings:
            click.echo(
                f"[code-compass] Semantic findings: {len(result.semantic_findings)} issue(s) identified."
            )

    slug = detect_github_slug(repo)
    if slug:
        click.echo(f"[code-compass] GitHub slug detected: {slug}")

    click.echo(f"[code-compass] Writing dashboard -> {out}")
    # render() validates the output path and raises ValueError for path-traversal
    # attempts (e.g. --output ../../../../etc/passwd or --output /etc/cron.d/evil).
    # Catch it here so the user sees a clean error instead of a raw traceback.
    try:
        written = render(result, out, repo_name=repo.name, github_slug=slug, github_ref=repo_ref)
        save_cache(hash_str, result, ttl_days=30, repo_name=repo.name, github_slug=slug or "")
    except ValueError as exc:
        click.echo(f"[code-compass] ERROR: {exc}", err=True)
        sys.exit(1)
    summary_name = written.stem + "-summary.html"
    click.echo(f"[code-compass] Dashboard written: {written}")
    click.echo(f"[code-compass] Summary written:   {written.parent / summary_name}")
    click.echo("[code-compass] Analysis complete.")


@main.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="Host to bind the web server to.")
@click.option("--port", default=8000, type=int, show_default=True, help="Port to listen on.")
def serve(host: str, port: int) -> None:
    """Launch the standalone Code Compass web application."""
    import uvicorn
    click.echo(f"[code-compass] Starting web server on http://{host}:{port}")
    uvicorn.run("code_compass.web.app:app", host=host, port=port, reload=False)

