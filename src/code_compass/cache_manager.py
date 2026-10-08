"""code_compass.cache_manager — opt-in Supabase caching for analysis results.

All public functions degrade gracefully to no-ops when the supabase package is
not installed or when SUPABASE_URL / SUPABASE_SERVICE_KEY env vars are absent.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
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


def _secret_key_config() -> tuple[str, str] | None:
    """Return the new server key; it must go in `apikey`, never Bearer auth."""
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    if url and key.startswith("sb_secret_"):
        return url, key
    return None


def _secret_key_request(method: str, query: dict[str, str], row: dict | None = None) -> list:
    """Call PostgREST with an opaque Supabase secret key in the correct header."""
    config = _secret_key_config()
    if config is None:
        raise ValueError("Supabase secret key is not configured")
    url, key = config
    endpoint = f"{url}/rest/v1/analysis_cache?{urllib.parse.urlencode(query)}"
    headers = {"apikey": key, "Accept": "application/json"}
    if row is not None:
        headers.update({
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        })
    request = urllib.request.Request(
        endpoint, data=json.dumps(row).encode("utf-8") if row is not None else None,
        headers=headers, method=method,
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        body = response.read()
    return json.loads(body) if body else []


def load_cache(hash_str: str, ttl_days: int = 7) -> Optional[AnalysisResult]:
    """Return a cached :class:`AnalysisResult`, or *None* on any miss/error."""
    if _secret_key_config() is not None:
        try:
            rows = _secret_key_request("GET", {
                "repo_hash": f"eq.{hash_str}",
                "expires_at": f"gt.{datetime.now(timezone.utc).isoformat()}",
                "select": "analysis_json", "limit": "1",
            })
            if rows and isinstance(rows[0], dict) and rows[0].get("analysis_json"):
                return _dict_to_analysis_result(rows[0]["analysis_json"])
        except Exception as exc:
            print(f"CACHE LOAD FAILED: {type(exc).__name__}")
        return None

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
        if _secret_key_config() is not None:
            _secret_key_request("POST", {"on_conflict": "repo_hash"}, row)
            return True
        client = _get_client()
        if client is None:
            return False
        client.table("analysis_cache").upsert(row).execute()
        return True
    except Exception as e:
        print(f"CACHE SAVE FAILED: {type(e).__name__}"
              + (f" HTTP {e.code}" if isinstance(e, urllib.error.HTTPError) else ""))
        return False
