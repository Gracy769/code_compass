"""Semantic audit integration point.

No provider is configured yet. Returning no findings is safer than presenting
deterministic example vulnerabilities as findings about a user's code.
"""

from __future__ import annotations

from pathlib import Path

from code_compass.analysis.models import AnalysisResult, SemanticFinding


def run_semantic_audit(result: AnalysisResult, repo_root: Path) -> list[SemanticFinding]:
    """Return no findings until a real audit provider is implemented."""
    return []
