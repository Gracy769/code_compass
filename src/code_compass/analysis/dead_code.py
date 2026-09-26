"""code_compass.analysis.dead_code — dead symbol detection pass."""

from __future__ import annotations

from code_compass.analysis.models import AnalysisResult


def find_dead_code(result: AnalysisResult) -> list[str]:
    """Return a list of symbol names that are defined but never referenced.

    A symbol is considered *referenced* if its name appears as the callee of
    any :class:`~code_compass.analysis.models.CallEdge` in *result*.

    This is a conservative approximation: it operates on bare names (not
    qualified names), so it will not flag any symbol whose name is called
    anywhere in the repo — even from a different class or module.  This keeps
    false-positive rates low for public APIs.

    Only run when ``--strict`` is passed (controlled by the orchestrator).
    """
    referenced: set[str] = {edge.callee for edge in result.call_edges}
    dead: list[str] = []
    for sym in result.symbols:
        if sym.name not in referenced:
            dead.append(sym.name)
    return dead
