"""code_compass.analysis.git_stats — Git & GitHub-synced contributor statistics."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from pathlib import Path

from code_compass.analysis.models import ContributorStat


def detect_github_slug(root: Path) -> str:
    """Return the GitHub slug (``"owner/repo"``) for the repository at *root*.

    Checks (in order): git remote URL, ``pyproject.toml``, ``package.json``,
    ``CITATION.cff``, ``README.md``, then falls back to a folder-name heuristic
    (e.g. ``fastapi-master`` → ``"fastapi/fastapi"``).

    Returns an empty string if the slug cannot be determined.
    """
    pair = _detect_github_slug(root)
    return f"{pair[0]}/{pair[1]}" if pair else ""


def _detect_github_slug(root: Path) -> tuple[str, str] | None:
    """Attempt to detect the GitHub owner and repo name from git remote or metadata."""
    # 1. Try git remote
    try:
        from git import Repo
        repo = Repo(str(root), search_parent_directories=False)
        for remote in repo.remotes:
            for url in remote.urls:
                m = re.search(r"github\.com[:/]([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+?)(?:\.git)?$", url)
                if m:
                    return m.group(1), m.group(2)
    except Exception:
        pass

    # 2. Try pyproject.toml / package.json / README.md / CITATION.cff
    search_files = [
        root / "pyproject.toml",
        root / "package.json",
        root / "CITATION.cff",
        root / "README.md",
    ]
    for p in search_files:
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8", errors="ignore")
                # Look for repository = "https://github.com/owner/repo"
                m = re.search(r"github\.com/([a-zA-Z0-9_\-\.]+)/([a-zA-Z0-9_\-\.]+?)(?:[\"\'\s/#)]|$)", text)
                if m:
                    owner, repo = m.group(1), m.group(2).rstrip(".")
                    if owner.lower() not in ("actions", "features", "sponsors", "marketplace"):
                        return owner, repo
            except Exception:
                continue

    # 3. Fallback: folder name heuristic (e.g. fastapi-master -> fastapi/fastapi)
    dirname = root.name.lower()
    for suffix in ("-master", "-main", "-dev", "-latest"):
        if dirname.endswith(suffix):
            cand = dirname[: -len(suffix)]
            return cand, cand

    return None


def _fetch_github_api_contributors(owner: str, repo: str) -> list[ContributorStat]:
    """Fetch top 100 contributors, using only the token supplied for this run."""
    data = []
    line_stats: dict[str, tuple[int, int]] = {}
    headers = {
        "User-Agent": "Code-Compass-Agent/1.0",
        "Accept": "application/vnd.github+json",
    }
    token = os.environ.get("CODE_COMPASS_CLONE_TOKEN", "")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page=100"
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                data = json.loads(resp.read(1_000_001).decode("utf-8"))
    except Exception:
        data = []

    # GitHub computes weekly addition/deletion totals separately. A 202 starts
    # the calculation; give it two short chances to finish before using Git.
    if data:
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/stats/contributors"
            for attempt in range(3):
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=8) as resp:
                    if resp.status == 200:
                        details = json.loads(resp.read(5_000_001).decode("utf-8"))
                        if isinstance(details, list):
                            for item in details:
                                login = (item.get("author") or {}).get("login")
                                weeks = item.get("weeks", [])
                                if login and isinstance(weeks, list):
                                    line_stats[login] = (
                                        sum(int(week.get("a", 0)) for week in weeks),
                                        sum(int(week.get("d", 0)) for week in weeks),
                                    )
                        break
                    if resp.status != 202 or attempt == 2:
                        break
                time.sleep(attempt + 1)
        except Exception:
            pass

    if not isinstance(data, list):
        return []

    stats: list[ContributorStat] = []
    for i, item in enumerate(data[:100]):
        login = item.get("login") or f"Contributor-{i+1}"
        contribs = int(item.get("contributions", 1))
        stats.append(
            ContributorStat(
                author=login,
                commits=contribs,
                lines_added=line_stats.get(login, (0, 0))[0],
                lines_deleted=line_stats.get(login, (0, 0))[1],
                line_stats_available=login in line_stats,
                avatar_url=item.get("avatar_url", ""),
                github_handle=login,
                rank=i + 1,
            )
        )
    return stats


def collect_git_stats(root: Path, *, prefer_local: bool = False) -> list[ContributorStat]:
    """Return per-author commit and line-change stats for the repo at *root*.

    Use GitHub's contributor identities when its line totals are complete.
    Otherwise use full local history, so the displayed rows and line totals
    describe the same commits and authors.
    """
    stats_map: dict[str, dict] = {}
    has_local_git = False
    github_stats: list[ContributorStat] = []

    try:
        from git import InvalidGitRepositoryError, NoSuchPathError, Repo
        repo = Repo(str(root), search_parent_directories=False)
        has_local_git = True
    except Exception:
        has_local_git = False

    if has_local_git:
        # GitHub's weekly statistics can return 202 while being generated.
        # In that case, use local numstat only when the clone has full history.
        slug = _detect_github_slug(root)
        if slug and not prefer_local:
            github_stats = _fetch_github_api_contributors(*slug)
            if github_stats and all(c.line_stats_available for c in github_stats):
                # GitHub documents zeroed addition/deletion totals for repos
                # with 10,000+ commits; use Git history in that case.
                try:
                    if int(repo.git.rev_list("--count", "HEAD")) < 10_000:
                        return github_stats
                except Exception:
                    return github_stats
        try:
            if github_stats and repo.git.rev_parse("--is-shallow-repository").strip() == "true":
                return github_stats
        except Exception:
            # Older Git versions may not support this flag; avoid claiming
            # complete local totals when clone depth cannot be verified.
            if github_stats:
                return github_stats
        try:
            with repo:
                with repo.git.custom_environment(
                    GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS="0",
                ):
                    log_output: str = repo.git.log("--no-ext-diff", "--numstat", "--use-mailmap", "--format=%aE|%aN")
                current_author: str | None = None
                current_name: str = ""

                for line in log_output.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split("\t")
                    if len(parts) == 3:
                        if current_author is None:
                            continue
                        try:
                            added = int(parts[0])
                            deleted = int(parts[1])
                        except ValueError:
                            continue
                        stats_map[current_author]["lines_added"] += added
                        stats_map[current_author]["lines_deleted"] += deleted
                    else:
                        header_parts = line.split("|")
                        current_author = header_parts[0].strip()
                        current_name = header_parts[1].strip() if len(header_parts) > 1 else current_author
                        if current_author not in stats_map:
                            stats_map[current_author] = {
                                "name": current_name,
                                "commits": 0,
                                "lines_added": 0,
                                "lines_deleted": 0,
                            }
                        stats_map[current_author]["commits"] += 1
        except Exception:
            pass

    if stats_map:
        sorted_stats = sorted(stats_map.items(), key=lambda kv: -kv[1]["commits"])[:100]
        return [
            ContributorStat(
                author=data["name"] or email,
                commits=data["commits"],
                lines_added=data["lines_added"],
                lines_deleted=data["lines_deleted"],
                avatar_url="",
                github_handle="",
                rank=i + 1,
            )
            for i, (email, data) in enumerate(sorted_stats)
        ]

    return github_stats
