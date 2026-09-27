# Code Compass

Analyse a local Git repository and generate an interactive HTML dashboard, or use the browser interface to analyse a GitHub repository or a ZIP upload.

## Install and run

Requires Python 3.11 or newer and Git for GitHub ingestion.

```bash
pip install -e '.[test]'
code-compass analyze /path/to/repo
code-compass analyze /path/to/repo --output report.html --strict
code-compass serve --host 127.0.0.1 --port 8000
```

The CLI writes a dashboard and a companion `-summary.html` file. The HTML embeds analysis data, but its fonts and Mermaid diagram loader use external resources; keep both files together and use an internet connection for the full visual experience.

The web page accepts only `https://github.com/owner/repo` URLs or ZIP files up to 25 MB. ZIPs are subject to expanded size, file count, and per-file limits. Git analysis has a two-minute deadline and only two analysis jobs run at once. A browser session can see only its own results, which are stored temporarily and expire after 24 hours. The bundled demo remains public.

For a private GitHub repository, the page accepts a personal access token for one analysis. The token is sent to the Code Compass server and then to GitHub for cloning; it is not saved in browser local storage or in the Git remote URL. Use HTTPS when running the service outside localhost. This is a single-service session boundary, not an enterprise identity system.

## Capabilities and limits

- Python analysis uses the standard-library AST; JavaScript and TypeScript use tree-sitter.
- The dashboard shows symbols, call relationships, contributor statistics, file rankings, architecture diagrams and a structural complexity score. Call relationships and rankings are heuristics.
- Web Git analysis uses GitHub's contributor API when available, including real account names and commit counts. Addition/deletion totals come from GitHub's separate contributor statistics when ready; otherwise those values show a dash. The full fetched Git history is the fallback. A ZIP with an initialized `.git` directory shows contributors from its bundled commit history; a plain folder ZIP shows no contributors.
- The web dashboard's Semantic Audit tab lets you provide an OpenAI-compatible HTTPS chat completions endpoint, model ID, and one-time API key after analysis. It sends excerpts from up to 12 ranked source files to that provider, validates the returned file names and severities, and stores only findings in the temporary run. Verify every finding against the code. The CLI `--semantic` option still generates no findings because no provider is configured there.
- The small codebase map uses ranked files and detected calls from the analyzed repository. The architecture diagram shows up to 15 ranked files and 18 links; drag to pan and scroll to zoom.
- The AI System Prompt tab provides a bounded, repository-specific starting brief with indexed paths and static call hints. It labels inferred structure and any audit state; check the relevant source files before using it to make claims.
- The browser app is not an Electron desktop app and does not ingest a local folder path; use the CLI for local paths or upload a ZIP.

## Tests

```bash
python -m pytest -q
```

Install the package in editable mode first, or set `PYTHONPATH=src` when running directly from a checkout.
