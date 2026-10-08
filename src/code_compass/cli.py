"""code_compass.cli — entry point for the `code-compass` command."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from code_compass.analysis import analyze as run_analysis
from code_compass.discovery import discover
from code_compass.renderer import render


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
    help="Enable LLM-powered semantic audit on the top-5 most complex files (opt-in; requires token budget).",
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
        click.echo("[code-compass] Semantic audit: enabled (top-5 complex files)")

    manifest = discover(repo)
    total = len(manifest.files)
    parseable = sum(1 for f in manifest.files if not f.is_binary and not f.too_large)
    click.echo(
        f"[code-compass] Discovered {total} file(s) "
        f"({parseable} parseable, {total - parseable} skipped)."
    )

    click.echo("[code-compass] Analysing symbols…")
    result = run_analysis(manifest, strict=strict, semantic=semantic)

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

    click.echo(f"[code-compass] Writing dashboard -> {out}")
    # render() validates the output path and raises ValueError for path-traversal
    # attempts (e.g. --output ../../../../etc/passwd or --output /etc/cron.d/evil).
    # Catch it here so the user sees a clean error instead of a raw traceback.
    try:
        written = render(result, out, repo_name=repo.name)
    except ValueError as exc:
        click.echo(f"[code-compass] ERROR: {exc}", err=True)
        sys.exit(1)
    click.echo(f"[code-compass] Dashboard written: {written}")
    click.echo("[code-compass] Analysis complete.")
