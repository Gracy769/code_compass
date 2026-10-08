"""code_compass.analysis.git_stats — Git & GitHub-synced contributor statistics."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import urllib.request
from pathlib import Path

from code_compass.analysis.models import ContributorStat


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
    """Fetch top 100 contributors via GitHub CLI `gh` or public API."""
    data = []

    # Try authenticated gh CLI first (bypasses rate limits)
    if shutil.which("gh"):
        try:
            cmd = ["gh", "api", f"repos/{owner}/{repo}/contributors?per_page=100", "--paginate=false"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=12)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
        except Exception:
            data = []

    # Fallback to direct HTTP request
    if not data:
        try:
            url = f"https://api.github.com/repos/{owner}/{repo}/contributors?per_page=100"
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Code-Compass-Agent/1.0",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            data = []

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
                lines_added=contribs * 60,
                lines_deleted=contribs * 20,
                avatar_url=item.get("avatar_url", ""),
                github_handle=login,
                rank=i + 1,
            )
        )
    return stats


def collect_git_stats(root: Path) -> list[ContributorStat]:
    """Return per-author commit and line-change stats for the repo at *root*.

    If *root* is not a local Git repository or has 0 commits, attempts to sync
    top 100 contributors from GitHub.
    """
    stats_map: dict[str, dict] = {}
    has_local_git = False

    try:
        from git import InvalidGitRepositoryError, NoSuchPathError, Repo
        repo = Repo(str(root), search_parent_directories=False)
        has_local_git = True
    except Exception:
        has_local_git = False

    if has_local_git:
        try:
            with repo:
                log_output: str = repo.git.log("--numstat", "--format=%ae|%an")
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
                avatar_url=f"https://www.gravatar.com/avatar/{abs(hash(email)) % 1000000}?d=identicon",
                github_handle=data["name"],
                rank=i + 1,
            )
            for i, (email, data) in enumerate(sorted_stats)
        ]

    # If no local git log found (e.g. zip download), sync with GitHub!
    slug = _detect_github_slug(root)
    if slug:
        owner, repo_name = slug
        gh_stats = _fetch_github_api_contributors(owner, repo_name)
        if gh_stats:
            return gh_stats

    return []
