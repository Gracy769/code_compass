# Code Compass

> Analyse any local Git repository and get a self-contained HTML dashboard in one command.

## Install

```bash
pip install -e .
# or, once published:
pip install code-compass
```

## Usage

```bash
# Basic — writes compass-dashboard.html in the current directory
code-compass /path/to/your/repo

# Custom output path
code-compass /path/to/your/repo --output report.html

# Enable dead-code detection (opt-in, may produce false positives on public APIs)
code-compass /path/to/your/repo --strict
```

## What it produces

A zero-dependency HTML file containing:

- **Overview** — file counts, top language, top contributor
- **Files** — sortable table with language, size, and complexity score
- **Symbols** — functions and classes with cyclomatic complexity and dead-code flags
- **Call Graph** — inter-file call relationships visualised with Chart.js
- **Contributors** — per-author commit and line stats from `git log`

## Supported languages

| Language | Parser |
|---|---|
| Python | stdlib `ast` |
| JavaScript | `tree-sitter-languages` |
| TypeScript / TSX / JSX | `tree-sitter-languages` |
