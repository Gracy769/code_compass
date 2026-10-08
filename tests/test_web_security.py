"""Regression checks for hosted ingestion and run isolation."""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

import code_compass.web.app as web_module
import code_compass.web.security as security
from code_compass.web.security import canonical_github_url, extract_zip_safely


@pytest.mark.parametrize("url", [
    "http://github.com/o/r", "https://127.0.0.1/o/r", "https://github.com.evil.test/o/r",
    "https://github.com@evil.test/o/r", "https://github.com/o/r/tree/main",
    "https://github.com/o/r?x=1", "git@github.com:o/r", "https://github.com/o/../r",
])
def test_only_canonical_github_repository_urls(url):
    with pytest.raises(ValueError):
        canonical_github_url(url)


def test_canonical_github_url():
    assert canonical_github_url("https://github.com/fastapi/fastapi") == "https://github.com/fastapi/fastapi.git"


def test_zip_traversal_rejected(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../repo-other/escape.py", "pass")
    with pytest.raises(ValueError, match="unsafe"):
        extract_zip_safely(archive, tmp_path / "repo")


def test_zip_expansion_limit(tmp_path, monkeypatch):
    archive = tmp_path / "large.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("large.py", "pass")
    monkeypatch.setattr(security, "MAX_EXTRACTED_BYTES", 2)
    with pytest.raises(ValueError, match="size limit"):
        extract_zip_safely(archive, tmp_path / "repo")


@pytest.mark.parametrize("name,body", [
    ("repo/.git", "gitdir: C:/elsewhere"),
    ("repo/.git/objects/info/alternates", "C:/elsewhere"),
    ("repo/.git/config", '[include]\npath = C:/elsewhere/config\n'),
])
def test_zip_rejects_external_git_metadata(tmp_path, name, body):
    archive = tmp_path / "bad-git.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(name, body)
    with pytest.raises(ValueError, match="unsupported Git"):
        extract_zip_safely(archive, tmp_path / "repo")


def test_runs_are_private_and_unknown_ids_do_not_redirect(tmp_path, monkeypatch):
    monkeypatch.setattr(web_module, "STORAGE_DIR", tmp_path)
    with TestClient(web_module.app, base_url="https://testserver") as owner:
        assert owner.post("/api/analyze-git", json={"url": "https://github.com/o/r"}).status_code == 403
        home = owner.get("/")
        assert "secure" in home.headers["set-cookie"].lower()
        assert owner.post(
            "/api/analyze-git", json={"url": "https://github.com/o/r"},
            headers={"Origin": "https://attacker.example"},
        ).status_code == 403
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as zf:
            zf.writestr("sample/main.py", "def greet():\n    return 'hello'\n")
        response = owner.post("/api/analyze-upload", files={"file": ("sample.zip", blob.getvalue(), "application/zip")})
        assert response.status_code == 200, response.text
        run_id = response.json()["analysis_id"]
        dashboard = owner.get(f"/dashboard/{run_id}")
        assert dashboard.status_code == 200
        assert dashboard.headers["cache-control"] == "private, no-store"
        assert f"/summary/{run_id}" in dashboard.text
        assert str(tmp_path) not in dashboard.text
        assert owner.get(f"/summary/{run_id}").status_code == 200
        assert owner.get("/dashboard/run_000000000000").status_code == 404
        async def audit_stub(kind, source, run_dir, **settings):
            assert kind == "audit" and run_dir == tmp_path / run_id
            assert settings["model"] == "test-model"
            assert settings["api_key"] == "one-time-key"

        monkeypatch.setattr(web_module, "_bounded_worker", audit_stub)
        assert owner.post(f"/api/audit/{run_id}", json={
            "endpoint": "https://api.example.com/v1/chat/completions",
            "model": "test-model", "api_key": "one-time-key",
        }).status_code == 200
        with TestClient(web_module.app, base_url="https://testserver") as outsider:
            outsider.get("/")
            assert outsider.get(f"/dashboard/{run_id}").status_code == 404
            assert outsider.get(f"/summary/{run_id}").status_code == 404
            assert outsider.post(f"/api/audit/{run_id}", json={
                "endpoint": "https://api.example.com/v1/chat/completions",
                "model": "test", "api_key": "secret",
            }).status_code == 404
