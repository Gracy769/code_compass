"""Contributor lists must come from a verified source, not the clone depth."""

from __future__ import annotations

import json

from git import Actor, Repo

from code_compass.analysis import git_stats
from code_compass.analysis.models import ContributorStat


def test_github_contributors_take_priority_over_local_commit_slice(tmp_path, monkeypatch):
    repo = Repo.init(tmp_path)
    (tmp_path / "main.py").write_text("pass\n", encoding="utf-8")
    repo.index.add(["main.py"])
    actor = Actor("Test Author", "author@example.com")
    repo.index.commit("initial", author=actor, committer=actor)
    repo.create_remote("origin", "https://github.com/example/project.git")
    verified = [
        ContributorStat(author="first", commits=20, github_handle="first", line_stats_available=False),
        ContributorStat(author="second", commits=10, github_handle="second", line_stats_available=False),
    ]
    monkeypatch.setattr(git_stats, "_fetch_github_api_contributors", lambda owner, name: verified)
    assert git_stats.collect_git_stats(tmp_path) == verified


def test_zip_without_git_history_has_no_guessed_contributors(tmp_path):
    (tmp_path / "README.md").write_text("https://github.com/someone/else", encoding="utf-8")
    assert git_stats.collect_git_stats(tmp_path) == []


def test_github_weekly_totals_are_used_only_when_available(monkeypatch):
    class Response:
        status = 200

        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self, _limit):
            return json.dumps(self.payload).encode()

    def urlopen(request, timeout):
        if "/stats/contributors" in request.full_url:
            return Response([{"author": {"login": "alice"}, "weeks": [
                {"a": 12, "d": 3}, {"a": 4, "d": 2},
            ]}])
        return Response([
            {"login": "alice", "contributions": 5, "avatar_url": "https://example.com/a.png"},
            {"login": "bob", "contributions": 2, "avatar_url": "https://example.com/b.png"},
        ])

    monkeypatch.setattr(git_stats.urllib.request, "urlopen", urlopen)
    contributors = git_stats._fetch_github_api_contributors("owner", "repo")
    assert [(c.author, c.commits) for c in contributors] == [("alice", 5), ("bob", 2)]
    assert (contributors[0].lines_added, contributors[0].lines_deleted) == (16, 5)
    assert contributors[0].line_stats_available
    assert not contributors[1].line_stats_available
