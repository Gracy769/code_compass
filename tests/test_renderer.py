"""tests/test_renderer.py — ST-8 output validation tests for the HTML renderer."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from code_compass.analysis.models import AnalysisResult, ContributorStat
from code_compass.renderer import render


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _empty_result() -> AnalysisResult:
    """Return a minimal AnalysisResult with no symbols, edges, or contributors."""
    return AnalysisResult()


# ---------------------------------------------------------------------------
# test_output_file_created
# ---------------------------------------------------------------------------


def test_output_file_created(tmp_repo: Path) -> None:
    """`render()` must create the output HTML file at the specified path."""
    output = tmp_repo / "dashboard.html"
    result = _empty_result()

    render(result, output, repo_name="test-repo")

    assert output.exists(), f"Expected output file to exist at {output}"
    assert output.stat().st_size > 0, "Output HTML file is empty"


# ---------------------------------------------------------------------------
# test_output_is_self_contained
# ---------------------------------------------------------------------------


def test_output_is_self_contained(tmp_repo: Path) -> None:
    """Output HTML must contain no external <link> or <script src> tags other
    than the Chart.js CDN reference.

    All CSS and JS (except Chart.js loaded at browser-open time) must be inlined.
    """
    output = tmp_repo / "dashboard.html"
    render(_empty_result(), output, repo_name="test-repo")

    html = output.read_text(encoding="utf-8")

    # Collect all <link href="..."> tags (stylesheet external refs).
    external_links = re.findall(r'<link\b[^>]*\bhref\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
    for href in external_links:
        # Only data URIs are allowed in link tags.
        assert href.startswith("data:"), (
            f"External <link href> found in output (not self-contained): {href!r}"
        )

    # Collect all <script src="..."> tags.
    script_srcs = re.findall(r'<script\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)
    for src in script_srcs:
        # The only allowed external script is Chart.js via CDN.
        assert "chart.js" in src.lower() or "chartjs" in src.lower(), (
            f"Unexpected external <script src> found in output: {src!r}"
        )


# ---------------------------------------------------------------------------
# test_data_json_embedded
# ---------------------------------------------------------------------------


def test_data_json_embedded(tmp_repo: Path) -> None:
    """`window.__COMPASS_DATA__` must be present in the rendered HTML output."""
    output = tmp_repo / "dashboard.html"
    render(_empty_result(), output, repo_name="test-repo")

    html = output.read_text(encoding="utf-8")

    assert "window.__COMPASS_DATA__" in html, (
        "Expected 'window.__COMPASS_DATA__' to be embedded in the output HTML"
    )


# ---------------------------------------------------------------------------
# test_xss_author_name  (ST-9)
# ---------------------------------------------------------------------------


def test_xss_author_name(tmp_repo: Path) -> None:
    """A git author name containing a raw XSS payload must never appear
    unescaped in the rendered HTML output.

    The attack vector: a malicious repository sets a git author name to
    ``<script>alert(1)</script>``.  Code Compass collects this via GitPython
    and stores it in ``ContributorStat.author``.  The value travels through:

        ContributorStat.author
          → dataclasses.asdict()
          → json.dumps()          # renderer.py line 104
          → {{ data_json | tojson }}  # Jinja2 tojson: escapes <, >, &
          → window.__COMPASS_DATA__  # embedded JSON string in HTML
          → td(c.author)             # JS: sets textContent (not innerHTML)

    At every stage the raw string ``<script>alert(1)</script>`` must be
    escaped.  Specifically the literal byte sequence ``<script>`` must NOT
    appear anywhere in the output HTML.
    """
    xss_author = "<script>alert(1)</script>"

    result = AnalysisResult(
        contributors=[
            ContributorStat(
                author=xss_author,
                commits=42,
                lines_added=1000,
                lines_deleted=200,
            )
        ]
    )

    output = tmp_repo / "dashboard_xss.html"
    render(result, output, repo_name="xss-test-repo")

    html = output.read_text(encoding="utf-8")

    # The literal unescaped payload must not be present.
    assert xss_author not in html, (
        f"XSS payload {xss_author!r} found unescaped in rendered HTML output. "
        "Contributor author names must be JSON/HTML-escaped before reaching the DOM."
    )

    # Sanity-check: the author data IS present — just escaped.
    # json.dumps escapes < as \u003c and > as \u003e; Jinja2 tojson additionally
    # HTML-escapes them as \\u003c inside the JSON string literal in the HTML.
    assert "alert(1)" in html, (
        "Expected the alert(1) substring to appear (escaped) in the output — "
        "the author data appears to be missing entirely."
    )
