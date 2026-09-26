"""code_compass.analysis.semantic_auditor — targeted semantic audit via LLM prompts.

Selects the top-5 most complex files identified by the AST pass and constructs
structured security-audit prompts for each.  In Phase 1 the LLM call is a
deterministic stub (``_call_llm``); replace it with a real client in Phase 2
without changing any other code.
"""

from __future__ import annotations

from pathlib import Path

from code_compass.analysis.models import AnalysisResult, SemanticFinding, SymbolInfo

# ---------------------------------------------------------------------------
# Finding template pool (indices 0-3), rotated per file.
# ---------------------------------------------------------------------------
_POOL: list[dict[str, str]] = [
    {
        "category": "race_condition",
        "severity": "high",
        "summary": "Potential race condition on shared mutable state",
        "detail": (
            "Multiple code paths modify shared data without synchronisation primitives. "
            "In a concurrent execution context (threads, async tasks, or multiprocessing) "
            "this can lead to data corruption, inconsistent reads, or silent data loss. "
            "Consider using locks, queues, or immutable data structures to serialise access."
        ),
    },
    {
        "category": "state_mutation",
        "severity": "medium",
        "summary": "Unguarded in-place state mutation detected",
        "detail": (
            "One or more functions mutate an object that is passed in by reference without "
            "making a defensive copy. Callers that retain a reference to the original object "
            "will observe unexpected side-effects. Prefer returning new instances or use "
            "copy.deepcopy() for complex nested structures."
        ),
    },
    {
        "category": "error_handling",
        "severity": "medium",
        "summary": "Bare except or overly broad exception swallowed",
        "detail": (
            "Catching BaseException or bare `except:` suppresses KeyboardInterrupt, SystemExit, "
            "and other signals that callers rely on. Narrow the except clause to the expected "
            "exception type. If broad catching is intentional, at minimum re-raise after logging "
            "to preserve the signal chain."
        ),
    },
    {
        "category": "insecure_defaults",
        "severity": "high",
        "summary": "Insecure default or weak cryptographic primitive detected",
        "detail": (
            "A function uses a weak hashing algorithm (MD5/SHA-1), a static secret, a hard-coded "
            "seed, or an insecure default configuration value. These are exploitable in adversarial "
            "environments. Replace with SHA-256 or stronger, load secrets from environment variables "
            "or a vault, and use os.urandom() for entropy sources."
        ),
    },
]

_SOURCE_CAP = 8192  # bytes — same sniff cap used in discovery.py


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_prompt(file_path: str, symbols: list[SymbolInfo]) -> str:
    """Return a structured security-audit prompt for *file_path*."""
    try:
        source = Path(file_path).read_bytes()[:_SOURCE_CAP].decode("utf-8", errors="replace")
    except Exception:
        source = "[source unavailable]"

    symbol_lines = "\n".join(
        f"  - {s.name} ({s.kind}, complexity={s.complexity})" for s in symbols
    )

    return (
        "You are performing a security-focused semantic audit of a source file.\n\n"
        f"File: {file_path}\n\n"
        "Symbols identified by static analysis:\n"
        f"{symbol_lines}\n\n"
        "Source snippet (up to 8192 bytes):\n"
        "```\n"
        f"{source}\n"
        "```\n\n"
        "Please identify issues in each of the following four categories:\n"
        "  1. race_condition — concurrent access to shared mutable state\n"
        "  2. state_mutation — unguarded in-place mutation of caller-owned objects\n"
        "  3. error_handling — bare or overly-broad exception handling\n"
        "  4. insecure_defaults — weak cryptographic primitives or insecure defaults\n\n"
        "For each finding provide:\n"
        "  - severity: high | medium | low\n"
        "  - category: one of the four above\n"
        "  - summary: a single line (≤ 120 chars)\n"
        "  - detail: a multi-sentence explanation with remediation advice\n"
    )


def _call_llm(prompt: str, file_path: str, file_index: int) -> list[SemanticFinding]:
    """Phase 1 deterministic stub — returns 3 findings rotated from *_POOL*."""
    findings: list[SemanticFinding] = []
    for offset in range(3):
        template = _POOL[(file_index + offset) % len(_POOL)]
        findings.append(
            SemanticFinding(
                file=file_path,
                severity=template["severity"],
                category=template["category"],
                summary=template["summary"],
                detail=template["detail"],
                prompt_used=prompt,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_semantic_audit(result: AnalysisResult, repo_root: Path) -> list[SemanticFinding]:
    """Select the top-5 most complex files and run a semantic audit on each.

    Parameters
    ----------
    result:
        The populated :class:`AnalysisResult` produced by the AST pass.
    repo_root:
        Repository root (currently reserved for future use, e.g. resolving
        relative paths; not used by the Phase 1 stub).

    Returns
    -------
    list[SemanticFinding]
        Flattened list of all findings across the selected files.
    """
    # 1. Group symbols by file.
    file_to_symbols: dict[str, list[SymbolInfo]] = {}
    for sym in result.symbols:
        file_to_symbols.setdefault(sym.file, []).append(sym)

    # 2. Compute max complexity per file.
    file_max_complexity: dict[str, int] = {
        f: max(s.complexity for s in syms)
        for f, syms in file_to_symbols.items()
    }

    # 3. Sort descending by max complexity; take top 5.
    top_files = sorted(file_max_complexity, key=lambda f: file_max_complexity[f], reverse=True)[:5]

    # 4. Audit each selected file.
    all_findings: list[SemanticFinding] = []
    for file_index, file_path in enumerate(top_files):
        symbols_for_file = file_to_symbols[file_path]
        prompt = _build_prompt(file_path, symbols_for_file)
        findings = _call_llm(prompt, file_path, file_index)
        all_findings.extend(findings)

    # 5. Return flattened findings.
    return all_findings
