"""Repository-specific prompt and uploaded Git-history regressions."""

from __future__ import annotations

import json
import sys
import zipfile

from git import Actor, Repo

from code_compass.analysis import analyze
from code_compass.analysis.prompt import read_project_description
from code_compass.discovery import discover
from code_compass.web import worker


def test_prompt_uses_observed_files_without_claiming_unseen_architecture(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"description": "An editor for research notes"}))
    (tmp_path / "main.ts").write_text("function start() { return 1; }\nstart();\n")
    result = analyze(discover(tmp_path), semantic=False, prefer_local_contributors=True)
    prompt = result.ai_system_prompt
    assert '"main.ts"' in prompt
    assert "An editor for research notes" in prompt
    assert "Entry point candidates based on filenames" in prompt
    assert "not complete knowledge" in prompt
    assert "Semantic audit has not run" in prompt
    assert "JWT" not in prompt and "OAuth" not in prompt
    assert "complete structural knowledge" not in prompt


def test_readme_description_skips_badges_and_html(tmp_path):
    (tmp_path / "README.md").write_text(
        "# Paperling\n\n<img src=\"badge.png\">\n\n"
        "Paperling helps people organize research papers and their notes.\n"
    )
    assert read_project_description(tmp_path) == "Paperling helps people organize research papers and their notes."


def _run_zip(tmp_path, monkeypatch, *, with_git):
    source = tmp_path / "source"
    source.mkdir()
    (source / "src").mkdir()
    (source / "src" / "main.py").write_text("def answer():\n    return 42\n")
    if with_git:
        repo = Repo.init(source)
        repo.git.add("src/main.py")
        author = Actor("Real Author", "real@example.test")
        repo.index.commit("initial", author=author, committer=author)
        repo.create_remote("origin", "https://github.com/example/unrelated.git")
    archive = tmp_path / "source.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        for path in source.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(source).as_posix())
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(sys, "argv", ["worker", "zip", str(archive), str(run_dir), "--name", "Uploaded project"])
    worker.main()
    return json.loads((run_dir / "analysis.json").read_text(encoding="utf-8")), (
        run_dir / "dashboard.html"
    ).read_text(encoding="utf-8")


def test_plain_zip_shows_no_contributors(tmp_path, monkeypatch):
    data, dashboard = _run_zip(tmp_path, monkeypatch, with_git=False)
    assert data["contributors"] == []
    assert data["repo_stats"]["contributor_history"] == "Local folder no contributors"
    assert "Local folder — no contributors" in dashboard


def test_git_initialized_zip_uses_its_own_commit_history(tmp_path, monkeypatch):
    data, _ = _run_zip(tmp_path, monkeypatch, with_git=True)
    assert data["repo_stats"]["contributor_history"] == "Local Git history"
    assert len(data["contributors"]) == 1
    assert data["contributors"][0]["author"] == "Real Author"
    assert data["contributors"][0]["commits"] == 1
    assert data["contributors"][0]["github_handle"] == ""
    assert '"src/main.py"' in data["ai_system_prompt"]
    assert '"Uploaded project"' in data["ai_system_prompt"]
