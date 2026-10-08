"""Configured audits validate their endpoint and update only the saved run."""

from __future__ import annotations

import dataclasses
import json
import sys

import pytest

from code_compass.analysis.models import AnalysisResult, FileMetadata, SemanticFinding
from code_compass.analysis.semantic_auditor import _public_endpoint, audit_with_provider
from code_compass.renderer import render
from code_compass.web import worker


@pytest.mark.parametrize("endpoint", [
    "http://api.example.com/v1/chat/completions",
    "https://127.0.0.1/v1/chat/completions",
    "https://api.example.com:8443/v1/chat/completions",
    "https://api.example.com/v1/chat/completions?redirect=1",
    "https://api.example.com/v1/models",
])
def test_rejects_unsafe_or_non_chat_endpoints(endpoint):
    with pytest.raises(ValueError):
        _public_endpoint(endpoint)


def test_rejects_private_dns_result(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [(None, None, None, None, ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="non-public"):
        _public_endpoint("https://api.example.com/v1/chat/completions")


def test_audit_sends_bounded_source_and_keeps_only_valid_findings(tmp_path, monkeypatch):
    (tmp_path / "main.py").write_text("def hello():\n    return 1\n", encoding="utf-8")
    result = AnalysisResult(files=[FileMetadata(path="main.py", rank_score=10)])
    monkeypatch.setattr("code_compass.analysis.semantic_auditor._public_endpoint",
                        lambda url: ("api.example.com", "8.8.8.8", "/v1/chat/completions"))

    class Response:
        status = 200

        def read(self, _limit):
            return json.dumps({"choices": [{"message": {"content": json.dumps({"findings": [
                {"file": "main.py", "severity": "high", "category": "bug", "summary": "Issue", "detail": "Evidence"},
                {"file": "other.py", "severity": "high", "category": "bug", "summary": "Invented", "detail": "None"},
            ]})}}]}).encode()

    class Connection:
        def __init__(self, *_args):
            pass

        def request(self, _method, _path, body, headers):
            assert b"def hello()" in body
            assert headers["Authorization"] == "Bearer secret"

        def getresponse(self):
            return Response()

        def close(self):
            pass

    monkeypatch.setattr("code_compass.analysis.semantic_auditor._PinnedHTTPSConnection", Connection)
    findings = audit_with_provider(result, tmp_path, endpoint="https://api.example.com/v1/chat/completions",
                                   model="test-model", api_key="secret")
    assert len(findings) == 1
    assert findings[0].file == "main.py"


def test_audit_worker_rerenders_existing_run_without_saving_key(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('ok')", encoding="utf-8")
    result = AnalysisResult(files=[FileMetadata(path="main.py")])
    (tmp_path / "analysis.json").write_text(json.dumps(dataclasses.asdict(result)), encoding="utf-8")
    (tmp_path / "analysis-meta.json").write_text(json.dumps({
        "target": "repo", "render": {"repo_name": "sample", "github_slug": "", "github_ref": ""},
    }), encoding="utf-8")
    render(result, tmp_path / "dashboard.html", repo_name="sample")
    monkeypatch.setattr(worker, "audit_with_provider", lambda *_args, **_kwargs: [
        SemanticFinding(file="main.py", severity="medium", category="bug", summary="Found issue", detail="Detail")
    ])
    monkeypatch.setenv("CODE_COMPASS_AUDIT_KEY", "secret-key")
    monkeypatch.setattr(sys, "argv", ["worker", "audit", ".", str(tmp_path), "--endpoint", "https://api.example.com/v1/chat/completions", "--model", "test-model"])
    worker.main()
    html = (tmp_path / "dashboard.html").read_text(encoding="utf-8")
    assert "Found issue" in html
    assert "dashboard-summary.html" in html
    assert "dashboard.next-summary.html" not in html
    assert "secret-key" not in html
    assert json.loads((tmp_path / "analysis.json").read_text())["repo_stats"]["semantic_status"] == "available"
