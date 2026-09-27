"""code_compass.cache_manager — opt-in Supabase caching for analysis results.

All public functions degrade gracefully to no-ops when the supabase package is
not installed or when SUPABASE_URL / SUPABASE_SERVICE_KEY env vars are absent.
"""

from __future__ import annotations

import dataclasses
import hashlib
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from code_compass.analysis.models import (
    AnalysisResult,
    CallEdge,
    ContributorStat,
    FileMetadata,
    SemanticFinding,
    SymbolInfo,
)

# ---------------------------------------------------------------------------
# Optional supabase import — no hard dependency
# ---------------------------------------------------------------------------

try:
    from supabase import Client, create_client  # type: ignore

    _SUPABASE_AVAILABLE = True
except ImportError:
    _SUPABASE_AVAILABLE = False
    Client = None  # type: ignore
    create_client = None  # type: ignore

# Module-level cached client (created at most once per process).
_client: Optional["Client"] = None  # type: ignore[type-arg]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _get_client() -> Optional["Client"]:  # type: ignore[type-arg]
    """Return a cached Supabase client, or *None* if unavailable/unconfigured."""
    global _client

    if not _SUPABASE_AVAILABLE:
        return None

    if _client is not None:
        return _client

    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return None

    try:
        _client = create_client(url, key)
        return _client
    except Exception:
        return None


def _dict_to_analysis_result(data: dict) -> AnalysisResult:
    """Reconstruct an :class:`AnalysisResult` from a plain dict (e.g. from JSON)."""
    return AnalysisResult(
        symbols=[SymbolInfo(**s) for s in data.get("symbols", [])],
        call_edges=[CallEdge(**e) for e in data.get("call_edges", [])],
        contributors=[ContributorStat(**c) for c in data.get("contributors", [])],
        parse_errors=list(data.get("parse_errors", [])),
        dead_code=list(data.get("dead_code", [])),
        semantic_findings=[SemanticFinding(**f) for f in data.get("semantic_findings", [])],
        files=[FileMetadata(**fm) for fm in data.get("files", [])],
        architecture_mermaid=data.get("architecture_mermaid", ""),
        ai_system_prompt=data.get("ai_system_prompt", ""),
        repo_stats=dict(data.get("repo_stats", {})),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_hash(repo_path_or_url: str, github_ref: str = "") -> str:
    """Return a stable 32-character hex digest for the given repo identifier."""
    return hashlib.sha256(
        f"{repo_path_or_url}:{github_ref}".encode()
    ).hexdigest()[:32]


def load_cache(hash_str: str, ttl_days: int = 7) -> Optional[AnalysisResult]:
    """Return a cached :class:`AnalysisResult`, or *None* on any miss/error."""
    client = _get_client()
    if client is None:
        return None

    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        response = (
            client.table("analysis_cache")
            .select("analysis_json")
            .eq("repo_hash", hash_str)
            .gt("expires_at", now_iso)
            .maybe_single()
            .execute()
        )
        if response is None or response.data is None:
            return None
        payload = response.data.get("analysis_json")
        if not payload:
            return None
        return _dict_to_analysis_result(payload)
    except Exception:
        return None


def save_cache(
    hash_str: str,
    result: AnalysisResult,
    ttl_days: int = 7,
    repo_name: str = "",
    github_slug: str = "",
) -> bool:
    """Upsert *result* into Supabase. Returns *True* on success, *False* otherwise."""
    client = _get_client()
    if client is None:
        return False

    try:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(days=ttl_days)
        row = {
            "repo_hash": hash_str,
            "repo_name": repo_name,
            "github_slug": github_slug,
            "analysis_json": dataclasses.asdict(result),
            "created_at": now.isoformat(),
            "expires_at": expires.isoformat(),
        }
        client.table("analysis_cache").upsert(row).execute()
        return True
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"CACHE SAVE FAILED: {e}")
        return False
