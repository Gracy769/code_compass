"""code_compass.renderer — render AnalysisResult to a self-contained HTML dashboard."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

# The directory that contains dashboard.html.j2
_TEMPLATES_DIR = Path(__file__).parent / "templates"

# Absolute path prefixes that are always off-limits for the output file.
# These cover sensitive system directories on Linux/macOS.  The check is
# skipped on Windows (drive letters make the comparison meaningless there,
# and Windows ACLs provide the primary protection).
_RESTRICTED_PREFIXES: tuple[Path, ...] = (
    Path("/etc"),
    Path("/root"),
    Path("/usr"),
    Path("/bin"),
    Path("/sbin"),
    Path("/boot"),
    Path("/sys"),
    Path("/proc"),
    Path("/dev"),
)


def _safe_output_path(output_path: Path) -> Path:
    """Resolve *output_path* and guard against path-traversal attacks.

    Rules
    -----
    * A **relative** path must resolve inside the current working directory.
      This blocks ``--output ../../../../etc/passwd``.
    * An **absolute** path is accepted only if it does not fall under a
      restricted system prefix (``/etc``, ``/root``, ``/usr``, ``/bin``,
      ``/sbin``, ``/boot``, ``/sys``, ``/proc``, ``/dev``).
      This blocks ``--output /etc/cron.d/evil`` even when the caller
      explicitly supplies a fully-qualified path.

    Raises :exc:`ValueError` on any violation.
    """
    resolved = output_path.resolve()
    cwd = Path.cwd().resolve()

    if not output_path.is_absolute():
        # Relative paths must stay inside cwd.
        try:
            resolved.relative_to(cwd)
        except ValueError:
            raise ValueError(
                f"Output path '{output_path}' resolves to '{resolved}', "
                f"which is outside the current working directory '{cwd}'. "
                "Use an absolute path or a path inside the current directory."
            )
    else:
        # Absolute paths must not target sensitive system directories.
        # The restriction only applies on POSIX systems where these prefixes
        # are meaningful; on Windows the check is skipped.
        import os
        if os.name == "posix":
            for prefix in _RESTRICTED_PREFIXES:
                try:
                    resolved.relative_to(prefix)
                except ValueError:
                    continue
                raise ValueError(
                    f"Output path '{output_path}' resolves to '{resolved}', "
                    f"which is under the restricted system prefix '{prefix}'. "
                    "Choose a path outside of system directories."
                )

    return resolved


def render(
    result: object,
    output_path: Path,
    *,
    repo_name: str = "",
    github_slug: str = "",
    github_ref: str = "",
) -> Path:
    """Serialize *result* (an :class:`~code_compass.analysis.models.AnalysisResult`)
    to JSON, render the Jinja2 dashboard and summary templates, and write both
    HTML files to disk.

    Parameters
    ----------
    result:
        An ``AnalysisResult`` dataclass instance.
    output_path:
        Destination ``.html`` file for the main dashboard.  Relative paths must
        resolve inside :func:`Path.cwd` to prevent path-traversal attacks.
    repo_name:
        Human-readable repository name shown in the dashboard title and nav bar.
    github_slug:
        Optional ``"owner/repo"`` slug used to build GitHub file links in the
        summary page (e.g. ``"fastapi/fastapi"``).  Defaults to ``""`` (no links).

    Returns
    -------
    Path
        The resolved, absolute path of the written dashboard file.
    """
    safe_path = _safe_output_path(output_path)
    summary_path = safe_path.parent / (safe_path.stem + "-summary.html")

    # Relative filename used in the dashboard → summary cross-link
    summary_url = safe_path.stem + "-summary.html"
    # Relative filename used in the summary → dashboard back-link
    dashboard_url = safe_path.name

    # Serialize: dataclasses.asdict() recurses into nested dataclasses and
    # produces plain dicts/lists that json.dumps handles directly.
    data_dict = dataclasses.asdict(result)
    data_json = json.dumps(data_dict)  # NOT marked safe — tojson filter escapes it

    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "j2"]),
    )

    # Shared template context
    ctx = dict(
        data_json=data_json,
        repo_name=repo_name,
        github_slug=github_slug,
        github_ref=github_ref,
        summary_url=summary_url,
        dashboard_url=dashboard_url,
    )

    # tojson is Jinja2's built-in filter; it HTML-escapes <, >, & inside JSON
    # strings, so even attacker-controlled repo content (e.g. a git author
    # name containing <script>) cannot break out of the JS string context.
    safe_path.parent.mkdir(parents=True, exist_ok=True)

    dashboard_html = env.get_template("dashboard.html.j2").render(**ctx)
    safe_path.write_text(dashboard_html, encoding="utf-8")

    summary_html = env.get_template("summary.html.j2").render(**ctx)
    summary_path.write_text(summary_html, encoding="utf-8")

    return safe_path
