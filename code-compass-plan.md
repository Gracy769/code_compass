# Code Compass — Execution Plan

## Top-Level Overview

**Goal:** Build `code-compass`, a pip-installable CLI tool that ingests any local Git repository, performs deep static analysis (AST parsing, call graphs, cyclomatic complexity, dead code detection, contributor stats), and emits a single self-contained HTML dashboard file.

**Runtime:** Python 3.11+  
**Distribution:** PyPI package (`pip install code-compass` / `pipx install code-compass`)  
**Output:** One zero-dependency HTML file with all CSS, JS, and JSON data inlined  
**AST Targets:** Python (stdlib `ast`) + JavaScript/TypeScript (`tree-sitter-languages` PyPI package — pre-compiled grammars, no C compiler required)
**Dashboard Style:** Glassmorphism base layer (Agent 4) + Claymorphism interactive elements (Agent 5)

**Non-Goals:**
- No live server / watch mode
- No cloud upload or remote storage
- No support beyond Python and JS/TS repos in v1
- No Jupyter notebook or binary-blob parsing
- Chart.js loaded via CDN at browser-open time (not inlined — keeps HTML file small)
- Dead code detection is opt-in via `--strict` CLI flag (avoids false positives on public APIs)

**Agent Responsibilities:**
| Agent | Role | Sub-Tasks Owned |
|---|---|---|
| 1 — Backend Lead | Core engine, CLI, file discovery, AST | ST-1, ST-2, ST-3 |
| 2 — Backend Reviewer | Code review, complexity audit | ST-4 |
| 3 — Frontend Architect | Dashboard HTML structure, routing | ST-5 (parallel with ST-4) |
| 4 — UI Designer (Glassmorphism) | Base CSS theme | ST-6 |
| 5 — UI Designer (Claymorphism) | Interactive/3D element layer | ST-6 |
| 6 — Red Team Lead | Path traversal, symlink, exec audit | ST-7 |
| 7 — Red Team Engineer | Performance / edge-case testing | ST-8 |
| 8 — Red Team Advisor | XSS / markdown sanitization audit | ST-9 |

---

## Sub-Task ST-1 — Project Scaffold & CLI Entry Point

**Agent:** Backend Lead (Agent 1)  
**Status:** [ ] pending

### Intent
Initialize the Python package with a standards-compliant `pyproject.toml`, establish the directory layout, and wire up the `code-compass` CLI entry point so the tool is installable immediately.

### Expected Outcomes
- `pip install -e .` succeeds in the repo root
- Running `code-compass --help` prints usage
- Running `code-compass <path>` prints a placeholder "Analysis complete" message
- `pyproject.toml` declares all runtime dependencies

### Todo List
1. Create `pyproject.toml` with `[project]` metadata, `requires-python = ">=3.11"`, dependencies list (`tree-sitter`, `tree-sitter-languages`, `click`, `gitpython`, `jinja2`), and `[project.scripts]` entry `code-compass = "code_compass.cli:main"`
2. Create `.gitignore` (Python standard: `__pycache__`, `*.egg-info`, `dist/`, `.venv/`)
3. Create `README.md` with one-line description and install/usage snippet
4. Create `src/code_compass/__init__.py` (empty)
5. Create `src/code_compass/cli.py` — `click` group with a single `analyze` command accepting a `repo_path` argument, `--output` option (default: `compass-dashboard.html`), and `--strict` flag (boolean, default `False`, enables dead code detection); command body is a placeholder stub
6. Verify `pip install -e .` resolves without errors

### Relevant Context
- Package source root: `src/code_compass/`
- Entry point: `src/code_compass/cli.py` → `main()`
- No existing files — greenfield

---

## Sub-Task ST-2 — File Discovery Engine

**Agent:** Backend Lead (Agent 1)  
**Status:** [ ] pending

### Intent
Build an optimized file-discovery engine that walks the repository, skips irrelevant paths, classifies every file by language, and returns a lightweight manifest — without loading file contents into memory.

### Expected Outcomes
- `discover(repo_path)` returns a `RepoManifest` dataclass in sub-second time on repos up to 50k files
- Binary files are detected by magic-byte sniff (not extension alone) and excluded from AST queue
- Symlinks are never followed (prevents traversal attacks — hardened here, audited in ST-7)
- `.gitignore` rules are respected
- Files larger than a configurable `MAX_FILE_BYTES` (default 512 KB) are excluded from AST parsing but counted in stats

### Todo List
1. Create `src/code_compass/discovery.py`
2. Define `FileRecord` dataclass: `path: Path`, `language: str | None`, `size_bytes: int`, `is_binary: bool`
3. Define `RepoManifest` dataclass: `root: Path`, `files: list[FileRecord]`, `skipped_dirs: list[str]`
4. Implement `_is_binary(path)` — read first 8 KB, check for null bytes
5. Implement `_classify_language(path)` — extension map (`{'.py': 'python', '.js': 'javascript', '.ts': 'typescript', '.tsx': 'typescript', '.jsx': 'javascript'}`); return `None` for unknown
6. Implement `discover(repo_path, max_file_bytes=524288)` using `os.scandir` (not `os.walk`) for minimal stat overhead; skip `SKIP_DIRS` set (`{'.git', 'node_modules', '__pycache__', '.venv', 'dist', 'build', '.next', 'vendor'}`); never follow symlinks (`os.scandir` entries: check `entry.is_symlink()`)
7. Wire `discover()` call into `cli.py` stub

### Relevant Context
- `src/code_compass/discovery.py`
- `src/code_compass/cli.py` (caller)
- Performance constraint: must handle 100k-file repos (Agent 7 will stress-test this)
- Security constraint: symlink following prohibited (Agent 6 will audit this)

---

## Sub-Task ST-3 — AST Analysis Engine

**Agent:** Backend Lead (Agent 1)  
**Status:** [ ] pending

### Intent
Build the multi-language static analysis engine that parses each source file in the manifest, extracts symbols (functions, classes, imports), computes cyclomatic complexity, detects potentially dead code, and builds an inter-file call graph.

### Expected Outcomes
- `analyze(manifest)` returns an `AnalysisResult` dataclass containing all extracted data
- Python files parsed with stdlib `ast`; JS/TS files parsed with `tree-sitter`
- Cyclomatic complexity computed per function (McCabe method)
- Dead code candidates: functions/classes defined but never referenced within the repo
- Call graph: dict mapping `caller_qualified_name → set[callee_name]`
- Git contributor stats collected via `GitPython` (`git log --numstat`)
- Files that fail to parse are logged as warnings and skipped, never crashing the run

### Todo List
1. Create `src/code_compass/analysis/__init__.py` — re-exports `analyze()`
2. Create `src/code_compass/analysis/models.py` — define dataclasses: `SymbolInfo` (name, kind, file, line, complexity), `CallEdge` (caller, callee), `ContributorStat` (author, commits, lines_added, lines_deleted), `AnalysisResult` (symbols, call_edges, contributors, parse_errors)
3. Create `src/code_compass/analysis/python_analyzer.py` — walk `ast.FunctionDef`/`ast.AsyncFunctionDef`/`ast.ClassDef` nodes; compute McCabe complexity by counting branch nodes (`If`, `For`, `While`, `ExceptHandler`, `With`, `BoolOp`, `Assert`); collect `ast.Call` nodes for call graph edges
4. Create `src/code_compass/analysis/js_analyzer.py` — initialize `tree-sitter` parser with `tree_sitter_languages.get_language('javascript')` / `'typescript'`; walk tree for `function_declaration`, `method_definition`, `class_declaration`; collect `call_expression` nodes
5. Create `src/code_compass/analysis/dead_code.py` — build `defined` set and `referenced` set from `AnalysisResult`; return symbols in `defined - referenced`
6. Create `src/code_compass/analysis/git_stats.py` — use `GitPython` `Repo(root).git.log('--numstat', '--format=%ae')` to accumulate per-author stats
7. Create `src/code_compass/analysis/orchestrator.py` — `analyze(manifest, strict=False)`: fan out per-file analysis, catch all parse exceptions, aggregate into `AnalysisResult`, run dead code pass only when `strict=True`, run git stats
8. Wire `analyze()` into `cli.py`

### Relevant Context
- `src/code_compass/analysis/` (new sub-package)
- Depends on `RepoManifest` from ST-2
- `tree-sitter-languages` bundles pre-compiled grammars — no grammar compilation step needed
- Complexity ceiling: files >512 KB already excluded by ST-2

---

## Sub-Task ST-4 — Backend Code Review

**Agent:** Backend Reviewer (Agent 2)  
**Status:** [ ] pending

### Intent
Systematically review the output of ST-1 through ST-3 for algorithmic inefficiencies, memory hazards, and correctness bugs before any frontend work begins.

### Expected Outcomes
- Review findings documented in `REVIEW-NOTES.md`
- Any blocking issues (O(n²) loops, unbounded memory, file-handle leaks) filed as specific fix items
- ST-2 and ST-3 amended to address all blocking findings
- Non-blocking findings noted but not actioned in v1

### Todo List
1. Create `REVIEW-NOTES.md`
2. Review `discovery.py`: verify `os.scandir` usage is iterative (no full list materialisation), symlink check is on `entry` not `path`, `_is_binary` closes its file handle
3. Review `analysis/orchestrator.py`: confirm no file contents held in memory after per-file parse completes; check for unbounded list growth in large repos
4. Review `analysis/python_analyzer.py`: confirm AST is not stored on `AnalysisResult` (only extracted primitives)
5. Review `analysis/js_analyzer.py`: confirm `tree-sitter` parser/language objects are singletons (not re-instantiated per file)
6. Review `analysis/git_stats.py`: confirm `GitPython` repo object is not leaking subprocess handles
7. Write findings and required amendments to `REVIEW-NOTES.md`
8. Apply all blocking amendments to the relevant source files

### Relevant Context
- `src/code_compass/discovery.py` (ST-2)
- `src/code_compass/analysis/` (ST-3)
- `REVIEW-NOTES.md` (new)

---

## Sub-Task ST-5 — Dashboard HTML Structure

**Agent:** Frontend Architect (Agent 3)  
**Status:** [ ] pending

### Intent
Design and implement the Jinja2 HTML template that structures the dashboard. The template receives the `AnalysisResult` as a JSON blob, inlines it as a JS variable, and uses vanilla JS for zero-build-step client-side tab routing and chart rendering.

### Expected Outcomes
- `src/code_compass/templates/dashboard.html.j2` is a complete, self-contained Jinja2 template
- Template receives one variable: `data_json` (the serialized `AnalysisResult`)
- Five tab sections: Overview, Files, Symbols, Call Graph, Contributors
- Tab routing implemented with pure vanilla JS (no framework, no bundler)
- Charts rendered with `Chart.js` loaded from a CDN `<script>` tag (one allowed external dep — loaded at open time, not at CLI time)
- All other CSS and JS is inlined in `<style>` and `<script>` blocks

### Todo List
1. Create `src/code_compass/templates/` directory
2. Create `src/code_compass/templates/dashboard.html.j2`
3. Write `<head>`: charset, viewport, title (`Code Compass — {{ repo_name }}`), inline `<style>` placeholder, Chart.js CDN script tag
4. Write `<body>`: top nav bar with app name + repo path; tab strip (`Overview | Files | Symbols | Call Graph | Contributors`); five `<section>` divs with matching IDs
5. Write **Overview section**: summary cards (total files, total symbols, top language, top contributor)
6. Write **Files section**: sortable table (filename, language, size, complexity score)
7. Write **Symbols section**: filterable table (symbol name, kind, file, line, complexity, dead-code flag)
8. Write **Call Graph section**: `<canvas>` element for Chart.js network; fallback text table
9. Write **Contributors section**: bar chart canvas + ranked table
10. Write inline `<script>` block: parse `window.__COMPASS_DATA__`; implement `showTab(id)` router; wire tab click handlers; initialize all Chart.js instances
11. Create `src/code_compass/renderer.py` — `render(result, output_path)`: serialize `AnalysisResult` to JSON, load template via Jinja2, write rendered HTML to `output_path`
12. Wire `renderer.render()` into `cli.py` as final step

### Relevant Context
- `src/code_compass/templates/dashboard.html.j2` (new)
- `src/code_compass/renderer.py` (new)
- `src/code_compass/analysis/models.py` — must be JSON-serializable
- Jinja2 is already a declared dependency (ST-1)

---

## Sub-Task ST-6 — Dashboard Visual Design

**Agents:** UI Designer Glassmorphism (Agent 4) + UI Designer Claymorphism (Agent 5)  
**Status:** [ ] pending

### Intent
Apply the full visual design system to the dashboard template. Agent 4 owns the base glassmorphism layer (frosted panels, transparency, blur). Agent 5 owns the claymorphism interactive layer (3D depth on cards, soft shadows, tactile button press). Both layers are delivered as a single cohesive inline `<style>` block.

### Expected Outcomes
- The `<style>` block in `dashboard.html.j2` is fully populated
- Background: deep dark gradient with a subtle animated noise/grain texture
- Cards/panels: `backdrop-filter: blur(16px)`, semi-transparent backgrounds, subtle border highlight (`rgba(255,255,255,0.12)`)
- Buttons and tab triggers: claymorphism treatment — `border-radius: 1.2rem`, layered `box-shadow` (outer highlight + deep drop shadow), `transform: translateY(-2px)` on hover, `transform: translateY(1px)` on active (press feedback)
- Table rows: alternating frosted row tints, hover glow
- Typography: system font stack, clear hierarchy (xl headings → base body → xs labels)
- Color tokens defined as CSS custom properties on `:root`
- Fully responsive: single-column on mobile, multi-column grid on desktop

### Todo List
1. Define `:root` CSS custom properties: `--glass-bg`, `--glass-border`, `--blur-radius`, `--clay-shadow`, `--clay-highlight`, `--accent`, `--accent-muted`, `--text-primary`, `--text-secondary`, `--surface`
2. Style `body`: dark gradient background, font stack, min-height
3. Style `.nav-bar`: glassmorphism panel — blurred, semi-transparent, sticky top
4. Style `.tab-strip` and `.tab-btn`: default glass state + claymorphism active/hover states with `box-shadow` depth layers
5. Style `.section-card` (wrapper for each tab's content): glass panel with `backdrop-filter`, rounded corners, `border: 1px solid var(--glass-border)`
6. Style `table`: frosted row backgrounds, sticky header, hover glow row effect
7. Style `.stat-card` (summary cards in Overview): claymorphism — large border-radius, layered shadows, subtle gradient fill
8. Style Chart.js canvas containers: glass card wrapper with inner padding
9. Style scrollbars (webkit): match theme
10. Add `@media (max-width: 768px)` responsive overrides: collapse grid to single column, reduce blur for perf
11. Insert the completed `<style>` block into `dashboard.html.j2`

### Relevant Context
- `src/code_compass/templates/dashboard.html.j2` (ST-5 must complete first)

---

## Sub-Task ST-7 — Security Audit (Red Team Lead)

**Agent:** Red Team Lead (Agent 6)  
**Status:** [ ] pending

### Intent
Audit the CLI for local filesystem security vulnerabilities: path traversal, symlink attacks, and any vector that could cause the tool to read or execute files outside the target repository.

### Expected Outcomes
- Security findings documented in `SECURITY-AUDIT.md`
- All critical and high findings fixed in source before v1 ship
- Path resolution hardened: final resolved path always confirmed to be inside `repo_root`

### Todo List
1. Create `SECURITY-AUDIT.md`
2. Audit `discovery.py`: verify `entry.is_symlink()` check is evaluated before `entry.is_dir()` (order matters — `is_dir()` follows symlinks by default); confirm `os.scandir` never follows symlink dirs
3. Audit CLI `repo_path` input: verify `Path(repo_path).resolve()` is called and result is checked to exist and be a directory before any traversal begins
4. Audit `git_stats.py`: verify no shell=True subprocess calls; `GitPython` uses its own safe subprocess wrapper — confirm no raw `subprocess.run` with user-controlled strings
5. Audit `renderer.py`: verify `output_path` is resolved and not allowed to point outside CWD or a user-specified safe directory (prevent `--output ../../../../etc/passwd` style attacks)
6. Audit Jinja2 template rendering: confirm `autoescape=True` is set on the Jinja2 `Environment` (prevents server-side template injection if any user content ever reaches template variables)
7. Document all findings in `SECURITY-AUDIT.md` with severity (Critical / High / Medium / Low)
8. Apply fixes for Critical and High findings

### Relevant Context
- `src/code_compass/discovery.py` (ST-2)
- `src/code_compass/analysis/git_stats.py` (ST-3)
- `src/code_compass/cli.py` (ST-1)
- `src/code_compass/renderer.py` (ST-5)
- `SECURITY-AUDIT.md` (new)

---

## Sub-Task ST-8 — Performance & Edge-Case Testing (Red Team Engineer)

**Agent:** Red Team Engineer (Agent 7)  
**Status:** [ ] pending

### Intent
Write a comprehensive test suite that validates correctness under normal conditions and does not degrade catastrophically under adversarial inputs (100k files, binary blobs, deeply nested trees, circular symlinks, empty repos, repos with no supported languages).

### Expected Outcomes
- `tests/` directory with `pytest`-based test suite
- All tests pass with `pytest tests/`
- Discovery engine benchmarked: completes in <2 s on a synthetic 10k-file tree
- No `MemoryError` or hang on binary-heavy repos
- Graceful output (warning + partial dashboard) when zero parseable files exist

### Todo List
1. Create `tests/__init__.py`
2. Create `tests/conftest.py` — `tmp_repo` fixture that creates a temp directory tree using `tmp_path`
3. Create `tests/test_discovery.py`:
   - `test_skips_dotgit`: `.git/` directory not in manifest
   - `test_skips_node_modules`: `node_modules/` not traversed
   - `test_excludes_symlinks`: symlinked file/dir not in manifest
   - `test_binary_detection`: a file with null bytes classified as binary
   - `test_large_file_excluded_from_ast`: file >512 KB present in manifest but `is_binary=False`, marked with size; confirm analyzer skips it
   - `test_empty_repo`: empty directory returns manifest with zero files (no crash)
   - `test_10k_files_performance`: create 10,000 `.py` stubs, assert discovery completes in <2 s using `time.perf_counter`
4. Create `tests/test_analysis.py`:
   - `test_python_complexity_simple`: function with no branches = complexity 1
   - `test_python_complexity_branching`: function with 3 `if` statements = complexity 4
   - `test_dead_code_detection`: define a function never called = appears in dead code list
   - `test_parse_error_graceful`: file with syntax error is skipped, not a crash
   - `test_binary_blob_skipped`: `.py` file containing binary content does not crash analyzer
5. Create `tests/test_renderer.py`:
   - `test_output_file_created`: `render()` creates the output HTML file
   - `test_output_is_self_contained`: output HTML contains no external `<link>` or `<script src>` other than Chart.js CDN
   - `test_data_json_embedded`: `window.__COMPASS_DATA__` present in output
6. Add `pytest` and `pytest-benchmark` to `pyproject.toml` `[project.optional-dependencies]` under `test`

### Relevant Context
- `src/code_compass/discovery.py` (ST-2)
- `src/code_compass/analysis/` (ST-3)
- `src/code_compass/renderer.py` (ST-5)
- `tests/` (new)

---

## Sub-Task ST-9 — XSS & Markdown Sanitization Audit (Red Team Advisor)

**Agent:** Red Team Advisor (Agent 8)  
**Status:** [ ] pending

### Intent
Audit all paths where repository-derived content (file names, symbol names, commit messages, author emails) is placed into the HTML output. Ensure no user-controlled string can break out of its context and execute as JavaScript.

### Expected Outcomes
- XSS findings documented in `SECURITY-AUDIT.md` (appended to ST-7's file)
- All data injected into the HTML output is JSON-encoded (not raw string interpolation)
- Jinja2 `autoescape=True` confirmed (cross-references ST-7 finding)
- A proof-of-concept XSS payload test added to `tests/test_renderer.py`

### Todo List
1. Audit `renderer.py`: confirm `AnalysisResult` is serialized via `json.dumps()` and injected as `window.__COMPASS_DATA__ = {{ data_json | tojson }};` — the `tojson` Jinja2 filter HTML-escapes `<`, `>`, `&` inside JSON strings
2. Audit all Jinja2 template variables: confirm no variable is rendered with `{{ var | safe }}` unless explicitly reviewed
3. Audit contributor author names and commit messages: these are attacker-controlled (a malicious repo can have `<script>alert(1)</script>` as a git author name) — confirm they pass through `json.dumps` escaping before reaching the DOM
4. Audit the JS side: confirm the dashboard JS uses `textContent` / `createElement` (safe DOM APIs) not `innerHTML` when rendering table cells from `__COMPASS_DATA__`
5. Add `test_xss_author_name` to `tests/test_renderer.py`: inject `<script>alert(1)</script>` as a contributor name; assert the string is escaped in the output HTML (`&lt;script&gt;` or JSON-encoded `\u003cscript\u003e`)
6. Append XSS audit findings to `SECURITY-AUDIT.md`

### Relevant Context
- `src/code_compass/renderer.py` (ST-5)
- `src/code_compass/templates/dashboard.html.j2` (ST-5, ST-6)
- `tests/test_renderer.py` (ST-8)
- `SECURITY-AUDIT.md` (ST-7)

---

## Dependency Order

```
ST-1 (scaffold)
  └─► ST-2 (discovery)
        └─► ST-3 (AST analysis)
              ├─► ST-4 (backend review) ──► amendments to ST-2/ST-3  ─┐
              ├─► ST-5 (HTML structure) [runs in parallel with ST-4]  ─┤
              │         └─► ST-6 (visual design) ◄── waits for both ──┘
              │         └─► ST-8 (performance tests)
              │         └─► ST-9 (XSS audit)
              └─► ST-7 (security audit) ──► amendments to ST-1/ST-2/ST-3/ST-5
```

**Parallelism:** ST-4 (Backend Review) and ST-5 (HTML Structure) run in parallel — the Frontend Architect does not depend on the review outcome to build templates. ST-6, ST-8, and ST-9 wait for both ST-4 and ST-5 to complete.

ST-4, ST-7, ST-8, ST-9 are all gating reviews — no sub-task that follows them is considered complete until their blocking findings are resolved.
