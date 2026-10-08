"""code_compass.analysis.git_stats — GitPython-based contributor statistics."""

from __future__ import annotations

from pathlib import Path

from code_compass.analysis.models import ContributorStat


def collect_git_stats(root: Path) -> list[ContributorStat]:
    """Return per-author commit and line-change stats for the repo at *root*.

    Uses ``GitPython`` with ``Repo(root, search_parent_directories=False)``.
    If *root* is not a Git repository (or GitPython is unavailable), returns
    an empty list without raising.
    """
    try:
        from git import InvalidGitRepositoryError, NoSuchPathError, Repo
    except ImportError:
        return []

    try:
        repo = Repo(str(root), search_parent_directories=False)
    except (InvalidGitRepositoryError, NoSuchPathError):
        return []

    # Accumulate stats keyed by author email.
    # git log --numstat --format="%ae" prints the author email on its own line
    # followed by numstat lines (added\tdeleted\tfile) for each commit.
    stats: dict[str, dict] = {}  # email -> {commits, lines_added, lines_deleted}

    try:
        with repo:  # ensures repo.close() is called, releasing cat-file subprocess
            log_output: str = repo.git.log("--numstat", "--format=%ae")
    except Exception:  # noqa: BLE001 — any git error → return empty
        return []

    current_author: str | None = None

    for line in log_output.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split("\t")
        if len(parts) == 3:
            # numstat line: "<added>\t<deleted>\t<file>"
            added_str, deleted_str, _ = parts
            if current_author is None:
                continue
            try:
                added = int(added_str)
                deleted = int(deleted_str)
            except ValueError:
                # Binary file lines show '-' instead of a number — skip.
                continue
            entry = stats[current_author]
            entry["lines_added"] += added
            entry["lines_deleted"] += deleted
        else:
            # Author email line (from --format=%ae)
            current_author = line
            if current_author not in stats:
                stats[current_author] = {
                    "commits": 0,
                    "lines_added": 0,
                    "lines_deleted": 0,
                }
            stats[current_author]["commits"] += 1

    return [
        ContributorStat(
            author=email,
            commits=data["commits"],
            lines_added=data["lines_added"],
            lines_deleted=data["lines_deleted"],
        )
        for email, data in sorted(stats.items(), key=lambda kv: -kv[1]["commits"])
    ]
