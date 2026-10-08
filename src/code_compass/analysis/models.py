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
    tags: list[str] = field(default_factory=list)
    layer: str = "core"
    rank_score: float = 0.0


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
    lines_added: int = 0
    lines_deleted: int = 0
    avatar_url: str = ""
    github_handle: str = ""
    rank: int = 0
    line_stats_available: bool = True


@dataclass
class FileMetadata:
    """Architectural classification and ranking metadata for a single file."""

    path: str
    language: str = "python"
    size: int = 0
    complexity: int = 1
    symbols_count: int = 0
    layer: str = "core"
    ranking_tier: str = "Tier 3: Supporting"
    rank_score: float = 0.0
    in_degree: int = 0
    out_degree: int = 0
    tags: list[str] = field(default_factory=list)
    rank: int = 0


@dataclass
class SemanticFinding:
    """A single LLM-generated semantic audit finding for one source file."""

    file: str          # str (not Path) for JSON-serializability
    severity: str      # 'high' | 'medium' | 'low'
    category: str      # 'race_condition' | 'state_mutation' | 'error_handling' | 'insecure_defaults'
    summary: str       # one-line description (≤ 120 chars)
    detail: str        # multi-sentence explanation
    prompt_used: str = ""  # provenance label; no key or source excerpt is persisted


@dataclass
class AnalysisResult:
    """Top-level result returned by :func:`analyze`."""

    symbols: list[SymbolInfo] = field(default_factory=list)
    call_edges: list[CallEdge] = field(default_factory=list)
    contributors: list[ContributorStat] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    dead_code: list[str] = field(default_factory=list)
    semantic_findings: list[SemanticFinding] = field(default_factory=list)
    files: list[FileMetadata] = field(default_factory=list)
    architecture_mermaid: str = ""
    ai_system_prompt: str = ""
    repo_stats: dict[str, object] = field(default_factory=dict)
