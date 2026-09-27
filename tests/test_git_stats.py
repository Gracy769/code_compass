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
        ContributorStat(author="first", commits=20, github_handle="first", lines_added=30, line_stats_available=True),
        ContributorStat(author="second", commits=10, github_handle="second", lines_added=12, line_stats_available=True),
    ]
    monkeypatch.setattr(git_stats, "_fetch_github_api_contributors", lambda owner, name: verified)
    assert git_stats.collect_git_stats(tmp_path) == verified


def test_missing_github_line_totals_fall_back_to_complete_git_history(tmp_path, monkeypatch):
    repo = Repo.init(tmp_path)
    (tmp_path / "main.py").write_text("first\nsecond\n", encoding="utf-8")
    repo.index.add(["main.py"])
    actor = Actor("Real Author", "author@example.com")
    repo.index.commit("initial", author=actor, committer=actor)
    repo.create_remote("origin", "https://github.com/example/project.git")
    monkeypatch.setattr(git_stats, "_fetch_github_api_contributors", lambda owner, name: [
        ContributorStat(author="github-user", commits=1, github_handle="github-user", line_stats_available=False),
    ])

    contributors = git_stats.collect_git_stats(tmp_path)
    assert [(c.author, c.commits, c.lines_added, c.lines_deleted) for c in contributors] == [
        ("Real Author", 1, 2, 0),
    ]
    assert contributors[0].line_stats_available
    assert contributors[0].github_handle == ""


def test_local_history_retains_verified_github_avatar(tmp_path, monkeypatch):
    repo = Repo.init(tmp_path)
    (tmp_path / "main.py").write_text("first\nsecond\n", encoding="utf-8")
    repo.index.add(["main.py"])
    actor = Actor("Saqlain", "146865285+Razee4315@users.noreply.github.com")
    repo.index.commit("initial", author=actor, committer=actor)
    repo.create_remote("origin", "https://github.com/example/project.git")
    monkeypatch.setattr(git_stats, "_fetch_github_api_contributors", lambda owner, name: [
        ContributorStat(author="Razee4315", commits=1, github_handle="Razee4315",
                        avatar_url="https://avatars.githubusercontent.com/u/146865285?v=4",
                        line_stats_available=False),
    ])

    contributors = git_stats.collect_git_stats(tmp_path)
    assert len(contributors) == 1
    assert (contributors[0].commits, contributors[0].lines_added) == (1, 2)
    assert contributors[0].github_handle == "Razee4315"
    assert contributors[0].avatar_url.endswith("?v=4")


def test_large_blob_filtered_clone_keeps_verified_counts_without_slow_line_scan(tmp_path, monkeypatch):
    repo = Repo.init(tmp_path)
    actor = Actor("Real Author", "author@example.com")
    for text in ("first\n", "second\n"):
        (tmp_path / "main.py").write_text(text, encoding="utf-8")
        repo.index.add(["main.py"])
        repo.index.commit("change", author=actor, committer=actor)
    repo.create_remote("origin", "https://github.com/example/project.git")
    repo.git.config("remote.origin.promisor", "true")
    monkeypatch.setattr(git_stats, "MAX_FILTERED_NUMSTAT_COMMITS", 1, raising=False)
    verified = [ContributorStat(
        author="github-user", commits=2, github_handle="github-user",
        line_stats_available=False,
    )]
    monkeypatch.setattr(git_stats, "_fetch_github_api_contributors", lambda owner, name: verified)

    assert git_stats.collect_git_stats(tmp_path) == verified


def test_large_blob_filtered_clone_without_api_uses_real_commit_counts(tmp_path, monkeypatch):
    repo = Repo.init(tmp_path)
    actor = Actor("Real Author", "author@example.com")
    for text in ("first\n", "second\n"):
        (tmp_path / "main.py").write_text(text, encoding="utf-8")
        repo.index.add(["main.py"])
        repo.index.commit("change", author=actor, committer=actor)
    repo.create_remote("origin", "https://github.com/example/project.git")
    repo.git.config("remote.origin.promisor", "true")
    monkeypatch.setattr(git_stats, "MAX_FILTERED_NUMSTAT_COMMITS", 1, raising=False)
    monkeypatch.setattr(git_stats, "_fetch_github_api_contributors", lambda owner, name: [])

    contributors = git_stats.collect_git_stats(tmp_path)
    assert len(contributors) == 1
    assert (contributors[0].author, contributors[0].commits) == ("Real Author", 2)
    assert not contributors[0].line_stats_available


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


def test_github_weekly_totals_retry_pending_response(monkeypatch):
    class Response:
        def __init__(self, status, payload):
            self.status = status
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            pass

        def read(self, _limit):
            return json.dumps(self.payload).encode()

    attempts = []

    def urlopen(request, timeout):
        if "/stats/contributors" in request.full_url:
            attempts.append(1)
            if len(attempts) == 1:
                return Response(202, {})
            return Response(200, [{"author": {"login": "alice"}, "weeks": [{"a": 7, "d": 2}]}])
        return Response(200, [{"login": "alice", "contributions": 1}])

    monkeypatch.setattr(git_stats.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(git_stats.time, "sleep", lambda _seconds: None)
    contributors = git_stats._fetch_github_api_contributors("owner", "repo")
    assert len(attempts) == 2
    assert (contributors[0].lines_added, contributors[0].lines_deleted) == (7, 2)
