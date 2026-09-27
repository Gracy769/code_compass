"""Tests for code_compass.cache_manager."""

import re
from unittest.mock import MagicMock

import pytest

import code_compass.cache_manager as cache_manager
from code_compass.analysis.models import AnalysisResult
from code_compass.cache_manager import compute_hash, load_cache, save_cache


# ---------------------------------------------------------------------------
# compute_hash
# ---------------------------------------------------------------------------


def test_hash_stability():
    h1 = compute_hash("https://github.com/owner/repo", "abc123")
    h2 = compute_hash("https://github.com/owner/repo", "abc123")
    assert h1 == h2


def test_hash_length():
    result = compute_hash("some/path", "ref")
    assert len(result) == 32
    assert re.fullmatch(r"[0-9a-f]{32}", result) is not None


# ---------------------------------------------------------------------------
# load_cache / save_cache — no Supabase configured
# ---------------------------------------------------------------------------


def test_load_cache_no_supabase_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setattr(cache_manager, "_client", None)

    result = load_cache("anyhash")
    assert result is None


def test_save_cache_no_supabase_url(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setattr(cache_manager, "_client", None)

    minimal = AnalysisResult()
    result = save_cache("anyhash", minimal)
    assert result is False


# ---------------------------------------------------------------------------
# load_cache — with mocked Supabase client
# ---------------------------------------------------------------------------


def test_load_cache_hit(monkeypatch):
    analysis_json = {
        "symbols": [],
        "call_edges": [],
        "contributors": [],
        "parse_errors": [],
        "dead_code": [],
        "semantic_findings": [],
        "files": [],
        "architecture_mermaid": "",
        "ai_system_prompt": "",
        "repo_stats": {},
    }

    mock_response = MagicMock()
    mock_response.data = {"analysis_json": analysis_json}

    mock_client = MagicMock()
    (
        mock_client.table.return_value
        .select.return_value
        .eq.return_value
        .gt.return_value
        .maybe_single.return_value
        .execute.return_value
    ) = mock_response

    monkeypatch.setattr(cache_manager, "_get_client", lambda: mock_client)

    result = load_cache("somehash")
    assert isinstance(result, AnalysisResult)
    assert result.symbols == []
    assert result.architecture_mermaid == ""


def test_load_cache_miss(monkeypatch):
    mock_response = MagicMock()
    mock_response.data = None

    mock_client = MagicMock()
    (
        mock_client.table.return_value
        .select.return_value
        .eq.return_value
        .gt.return_value
        .maybe_single.return_value
        .execute.return_value
    ) = mock_response

    monkeypatch.setattr(cache_manager, "_get_client", lambda: mock_client)

    result = load_cache("misshash")
    assert result is None


# ---------------------------------------------------------------------------
# save_cache — with mocked Supabase client
# ---------------------------------------------------------------------------


def test_save_cache_success(monkeypatch):
    mock_client = MagicMock()
    # .table(...).upsert(...).execute() just returns a MagicMock (success)

    monkeypatch.setattr(cache_manager, "_get_client", lambda: mock_client)

    result = save_cache("somehash", AnalysisResult())
    assert result is True


def test_save_cache_error(monkeypatch):
    mock_client = MagicMock()
    mock_client.table.return_value.upsert.return_value.execute.side_effect = Exception("db error")

    monkeypatch.setattr(cache_manager, "_get_client", lambda: mock_client)

    result = save_cache("somehash", AnalysisResult())
    assert result is False
