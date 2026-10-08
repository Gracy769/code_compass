"""Regression checks for hosted ingestion and run isolation."""

from __future__ import annotations

import io
import zipfile
from types import SimpleNamespace

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


def test_cached_github_analysis_keeps_source_links(tmp_path, monkeypatch):
    monkeypatch.setattr(web_module, "STORAGE_DIR", tmp_path)
    ref = "a" * 40
    monkeypatch.setattr(web_module, "load_cache", lambda *_args, **_kwargs: SimpleNamespace(
        repo_stats={"github_ref": ref},
    ))
    rendered = []

    def render_stub(_result, path, **kwargs):
        rendered.append(kwargs)
        path.write_text("dashboard", encoding="utf-8")
        path.with_name("dashboard-summary.html").write_text("summary", encoding="utf-8")

    monkeypatch.setattr(web_module, "render", render_stub)
    with TestClient(web_module.app, base_url="https://testserver") as client:
        client.get("/")
        response = client.post("/api/analyze-git", json={"url": "https://github.com/o/r"})
    assert response.status_code == 200
    assert rendered[-1]["github_slug"] == "o/r"
    assert rendered[-1]["github_ref"] == ref


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


def test_zip_rejects_nested_archive(tmp_path):
    archive = tmp_path / "nested.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("repo/inner.zip", b"PK\x05\x06" + b"\x00" * 18)
    with pytest.raises(ValueError, match="nested archive"):
        extract_zip_safely(archive, tmp_path / "repo")


def test_zip_rejects_excessive_compression_ratio(tmp_path):
    archive = tmp_path / "bomb.zip"
    import zlib
    # Create a member whose declared file_size >> compress_size to trigger the ratio guard.
    raw = b"\x00" * 200_000  # 200 KB uncompressed
    compressed = zlib.compress(raw, level=9)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bomb.txt", raw)
    with zipfile.ZipFile(archive, "r") as zf:
        info = zf.getinfo("bomb.txt")
    # Only trigger if the actual ratio qualifies; if real compression isn't extreme enough,
    # monkeypatch the sizes to force the condition.
    if info.compress_size == 0 or info.compress_size / info.file_size >= 0.01:
        # Force the ratio by writing a fake ZipInfo with extreme ratio via monkeypatch
        import code_compass.web.security as sec
        original = sec.MAX_EXTRACTED_BYTES
        # Patch: write a fresh archive whose null-byte member compresses well enough
        archive2 = tmp_path / "bomb2.zip"
        # Use a ZipInfo with manipulated sizes to guarantee ratio test fires
        zi = zipfile.ZipInfo("nulls.txt")
        zi.compress_type = zipfile.ZIP_DEFLATED
        raw2 = b"\x00" * 500_000  # 500 KB of nulls — highly compressible
        with zipfile.ZipFile(archive2, "w") as zf2:
            zf2.writestr(zi, raw2)
        with zipfile.ZipFile(archive2, "r") as zf2:
            info2 = zf2.getinfo("nulls.txt")
        if info2.compress_size > 0 and info2.compress_size / info2.file_size < 0.01:
            with pytest.raises(ValueError, match="compression ratio"):
                extract_zip_safely(archive2, tmp_path / "repo2")
        else:
            pytest.skip("Platform zlib did not compress enough to trigger ratio guard")
    else:
        with pytest.raises(ValueError, match="compression ratio"):
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
        # Extract CSRF token from cookie jar for use in state-changing requests.
        csrf = owner.cookies.get("csrf_token", "")
        blob = io.BytesIO()
        with zipfile.ZipFile(blob, "w") as zf:
            zf.writestr("sample/main.py", "def greet():\n    return 'hello'\n")
        response = owner.post(
            "/api/analyze-upload",
            files={"file": ("sample.zip", blob.getvalue(), "application/zip")},
            headers={"X-CSRF-Token": csrf},
        )
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
