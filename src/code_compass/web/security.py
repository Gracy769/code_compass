"""Input and run-access boundaries for the hosted analysis service."""

from __future__ import annotations

import hmac
import re
import shutil
import stat
import time
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_EXTRACTED_BYTES = 200 * 1024 * 1024
MAX_ZIP_FILES = 10_000
MAX_ZIP_MEMBER_BYTES = 25 * 1024 * 1024
MAX_CLONE_SECONDS = 120
RUN_TTL_SECONDS = 24 * 60 * 60

_REPO_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


def canonical_github_url(value: str) -> str:
    """Accept only a GitHub repository HTTPS URL and discard no hidden parts."""
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.port is not None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Enter an https://github.com/owner/repo URL.")
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 2:
        raise ValueError("Enter a GitHub repository URL, without a subpath.")
    owner, repo = parts
    if repo.endswith(".git"):
        repo = repo[:-4]
    if any(part in {"", ".", ".."} or not _REPO_PART.fullmatch(part) for part in (owner, repo)):
        raise ValueError("Invalid GitHub owner or repository name.")
    return f"https://github.com/{owner}/{repo}.git"


def extract_zip_safely(archive: Path, destination: Path) -> None:
    """Extract ordinary files with strict path and resource limits."""
    destination = destination.resolve()
    count = 0
    total = 0
    with zipfile.ZipFile(archive) as zf:
        members = zf.infolist()
        if len(members) > MAX_ZIP_FILES:
            raise ValueError("ZIP contains too many entries.")
        for member in members:
            name = member.filename.replace("\\", "/")
            path = PurePosixPath(name)
            if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} or ":" in part for part in path.parts):
                raise ValueError("ZIP contains an unsafe path.")
            if (path.name == ".git" and not member.is_dir()) or path.parts[-4:] == (".git", "objects", "info", "alternates"):
                raise ValueError("ZIP contains unsupported Git metadata.")
            target = destination.joinpath(*path.parts).resolve()
            try:
                target.relative_to(destination)
            except ValueError as exc:
                raise ValueError("ZIP contains an unsafe path.") from exc
            mode = member.external_attr >> 16
            kind = stat.S_IFMT(mode)
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError("ZIP contains a link or special file.")
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            count += 1
            total += member.file_size
            if count > MAX_ZIP_FILES or member.file_size > MAX_ZIP_MEMBER_BYTES or total > MAX_EXTRACTED_BYTES:
                raise ValueError("ZIP exceeds the analysis size limit.")
            if path.parts[-2:] == (".git", "config"):
                config = zf.read(member)
                if re.search(rb"(?im)^\s*\[\s*include(?:if)?\b", config):
                    raise ValueError("ZIP contains unsupported Git configuration.")
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(member) as source, target.open("wb") as output:
                copied = 0
                while chunk := source.read(1024 * 1024):
                    copied += len(chunk)
                    if copied > member.file_size or copied > MAX_ZIP_MEMBER_BYTES:
                        raise ValueError("ZIP member exceeds its declared size.")
                    output.write(chunk)


def check_run_owner(run_dir: Path, session: str | None) -> bool:
    if not session:
        return False
    try:
        if time.time() - run_dir.stat().st_mtime > RUN_TTL_SECONDS:
            return False
        owner = (run_dir / "owner").read_text(encoding="ascii")
    except OSError:
        return False
    return hmac.compare_digest(owner, session)


def cleanup_expired_runs(storage_dir: Path, now: float) -> None:
    for run_dir in storage_dir.glob("run_*"):
        try:
            if run_dir.is_dir() and now - run_dir.stat().st_mtime > RUN_TTL_SECONDS:
                shutil.rmtree(run_dir)
        except OSError:
            continue
