"""code_compass.analysis.models — JSON-serializable result dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SymbolInfo:
    """A function, async function, or class extracted from a source file."""

    name: str
    kind: str          # 'function' | 'async_function' | 'class'
    file: str          # str (not Path) for JSON-serializability
    line: int
    complexity: int    # McCabe cyclomatic complexity (1 for classes / JS symbols)


@dataclass
class CallEdge:
    """A directional call relationship: *caller* calls *callee*."""

    caller: str   # qualified name, e.g. "module.function"
    callee: str   # bare callee name as it appears in the source


@dataclass
class ContributorStat:
    """Per-author git contribution summary."""

    author: str
    commits: int
    lines_added: int
    lines_deleted: int


@dataclass
class AnalysisResult:
    """Top-level result returned by :func:`analyze`."""

    symbols: list[SymbolInfo] = field(default_factory=list)
    call_edges: list[CallEdge] = field(default_factory=list)
    contributors: list[ContributorStat] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    dead_code: list[str] = field(default_factory=list)
