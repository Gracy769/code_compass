# Phase 1 — Hybrid Agentic Engine: Execution Plan

## Approved Design Decisions (post-review)

1. **`--semantic` is opt-in** — default is `False`; deterministic AST mode is unchanged when
   the flag is absent. Semantic analysis triggers only on explicit `--semantic` invocation.
2. **Stub returns 2–3 findings per file** — the mock rotates through a fixed pool of category
   templates to produce 2–3 distinct `SemanticFinding` objects per audited file, making the
   dashboard demo data-rich.
3. **Four audit categories** — `race_condition`, `state_mutation`, `error_handling`,
   `insecure_defaults` (covers cryptographic weaknesses). All four appear in `_build_prompt`
   and in the mock finding pool.

---

## Top-Level Overview

**Goal:** Evolve Code Compass from a purely deterministic AST tool into a Hybrid Agentic Engine.
The CLI will use existing AST complexity scores to select the **top 5 most complex files**, then pass
those files to a `SemanticAuditor` that generates (or mocks) LLM prompts and records structured audit
findings. The findings flow through the existing render pipeline and appear as a new "Semantic Audit"
tab in the HTML dashboard — zero breaking changes to the existing pipeline.

**Approach:** Follow the `dead_code` post-processing pattern exactly — a new module receives an
`AnalysisResult`, does its work, and returns a value that is stored in a new field on the result
dataclass. The orchestrator gains one new optional flag (`--semantic`). The renderer and template
require no structural changes beyond a new tab section and a new data variable.

**Scope:**
- New module: `src/code_compass/analysis/semantic_auditor.py`
- Data model: one new dataclass `SemanticFinding` + one new field on `AnalysisResult`
- Orchestrator: add one new optional pass (guarded by `semantic: bool = False`)
- CLI: add one new `--semantic` flag
- Template: add one new tab section + one `<script>` block (vanilla JS only)
- Tests: `tests/test_semantic.py` — unit tests for the new module

**Non-Goals:** No live LLM API key wiring in Phase 1 (mock/stub only). No refactor of existing
modules. No new external dependencies.

---

## Sub-Tasks

---

### Sub-Task 1 — Extend the Data Model

**Status:** [ ] pending

**Intent:**
Add the `SemanticFinding` dataclass and a `semantic_findings` field to `AnalysisResult`.
Every downstream module (orchestrator, renderer, template) will read this new field.
Doing the model first removes any import-order issues for the three parallel sub-tasks that follow.

**Expected Outcomes:**
- `SemanticFinding` dataclass exists in `models.py` with fields: `file`, `severity`,
  `category`, `summary`, `detail`, `prompt_used`.
- `AnalysisResult.semantic_findings` field exists, typed `list[SemanticFinding]`,
  defaults to empty list.
- `dataclasses.asdict(result)` already serialises the new field — no renderer changes needed.
- All existing tests still pass (new field is additive only).

**Todo List:**
1. Open `src/code_compass/analysis/models.py`.
2. Add `SemanticFinding` dataclass above `AnalysisResult` with fields:
   - `file: str` — source file path (relative, str for JSON)
   - `severity: str` — `"high"` | `"medium"` | `"low"`
   - `category: str` — e.g. `"race_condition"`, `"state_mutation"`, `"error_handling"`, `"mock"`
   - `summary: str` — one-line description (≤ 120 chars)
   - `detail: str` — multi-sentence explanation
   - `prompt_used: str` — the exact prompt sent to the LLM (or `"[mock]"` for stubs)
3. Add `semantic_findings: list[SemanticFinding] = field(default_factory=list)` to `AnalysisResult`.

**Relevant Context:**
- File: `src/code_compass/analysis/models.py`
- Pattern to follow: `ContributorStat` immediately above `AnalysisResult`

---

### Sub-Task 2 — Implement `semantic_auditor.py`

**Status:** [ ] pending

**Intent:**
Create the new `semantic_auditor` module. It accepts a completed `AnalysisResult` and the
repo root path, selects the top 5 files by maximum per-file cyclomatic complexity, constructs
a structured audit prompt for each file, and returns a list of `SemanticFinding` objects.
Phase 1 uses a deterministic mock strategy — a real LLM call is stubbed so the entire pipeline
runs offline and at zero cost. The module is written so that swapping the stub for a real LLM
client in Phase 2 requires changing only one private helper function.

**Expected Outcomes:**
- `src/code_compass/analysis/semantic_auditor.py` exists.
- `run_semantic_audit(result: AnalysisResult, repo_root: Path) -> list[SemanticFinding]` is the
  public entry point.
- The function computes `top_files` — the 5 files with the highest `max(symbol.complexity)`
  among all symbols grouped by `symbol.file`.
- For each file in `top_files`, it calls `_build_prompt(file_path, symbols)` to produce the
  prompt string, then calls `_call_llm(prompt, file_path)` which in Phase 1 returns a
  deterministic mock `SemanticFinding` with `category="mock"` and `severity="medium"`.
- If fewer than 5 parseable files exist, it audits all of them.
- File read errors inside `_build_prompt` are caught; the finding's `detail` records the
  error and execution continues.

**Todo List:**
1. Create `src/code_compass/analysis/semantic_auditor.py`.
2. Import `AnalysisResult`, `SemanticFinding` from `.models`; import `Path` from `pathlib`.
3. Write `_build_prompt(file_path: Path, symbols: list[SymbolInfo]) -> str`:
   - Read the file source (up to 8 KB max to avoid token blowout).
   - Build a structured prompt string that lists the file's symbol names and complexities,
     then appends the source snippet and asks for race conditions, state mutation flaws,
     and error-handling gaps.
4. Write `_call_llm(prompt: str, file_path: str) -> SemanticFinding` (Phase 1 stub):
   - Returns a `SemanticFinding` with `category="mock"`, `severity="medium"`,
     `summary="[Mock] Semantic audit placeholder"`,
     `detail="Phase 1 stub — replace _call_llm with a real LLM client in Phase 2."`,
     `prompt_used=prompt`.
5. Write `run_semantic_audit(result: AnalysisResult, repo_root: Path) -> list[SemanticFinding]`:
   - Group symbols by `symbol.file`.
   - Compute `max_complexity` per file; sort descending; take top 5.
   - For each, call `_build_prompt` then `_call_llm`; collect results.
   - Return the list.

**Relevant Context:**
- Reference pattern: `src/code_compass/analysis/dead_code.py` — takes `AnalysisResult`, returns list
- `SymbolInfo.file` is a `str` (not `Path`); convert when reading file content
- 8 KB read cap matches the existing binary-detection sniff size in `discovery.py`

---

### Sub-Task 3 — Wire into the Orchestrator and CLI

**Status:** [ ] pending

**Intent:**
Expose the new semantic pass through the orchestrator (guarded by `semantic=False`) and add a
`--semantic` CLI flag. This follows the exact same pattern as the existing `strict`/`dead_code`
pairing.

**Expected Outcomes:**
- `orchestrator.analyze()` accepts `semantic: bool = False`.
- When `semantic=True`, the orchestrator calls `run_semantic_audit(result, manifest.root)` and
  stores the return value in `result.semantic_findings`.
- `cli.py` gains `--semantic` flag; when set, it passes `semantic=True` to `analyze()` and
  echoes a count of findings found.
- All existing tests still pass (new parameter has `False` default).

**Todo List:**
1. Open `src/code_compass/analysis/orchestrator.py`.
2. Import `run_semantic_audit` from `.semantic_auditor`.
3. Add `semantic: bool = False` parameter to `analyze()`.
4. After the dead-code block, add:
   ```python
   if semantic:
       result.semantic_findings = run_semantic_audit(result, manifest.root)
   ```
5. Open `src/code_compass/cli.py`.
6. Add `--semantic` click option (is_flag, default False, help text explaining token-saving rationale).
7. Pass `semantic=semantic` to `run_analysis()`.
8. After the existing dead-code echo, add semantic findings count echo when `semantic` is True.

**Relevant Context:**
- `src/code_compass/analysis/orchestrator.py` lines 44-50 — dead_code block to mirror
- `src/code_compass/cli.py` lines 28-33 — existing `--strict` flag as exact pattern to follow
- `src/code_compass/analysis/__init__.py` re-exports `analyze()` — no change needed there

---

### Sub-Task 4 — Update the Dashboard Template

**Status:** [ ] pending

**Intent:**
Add a "Semantic Audit" tab to `dashboard.html.j2` that renders the `semantic_findings` list.
Because `dataclasses.asdict()` already serialises the new field into `data_json`, no changes to
`renderer.py` are needed. The tab follows the existing section + vanilla-JS pattern exactly.

**Expected Outcomes:**
- A sixth tab button "Semantic Audit" appears in the tab strip.
- The new `tab-semantic` section contains a severity-filtered table with columns:
  File, Severity, Category, Summary, and an expandable Detail cell.
- Severity badges use existing CSS colour tokens: `--danger` (high), `--warn` (medium),
  `--success` (low).
- If `semantic_findings` is empty, a friendly empty-state message is shown instead of a table.
- All existing tabs are unchanged; all existing tests still pass.

**Todo List:**
1. Open `src/code_compass/templates/dashboard.html.j2`.
2. In the tab strip (line ~494), add after the Contributors button:
   ```html
   <button class="tab-btn" role="tab" aria-selected="false"
           aria-controls="tab-semantic" data-tab="semantic">Semantic Audit</button>
   ```
3. In the tab content section, after the Contributors `<section>`, add a new
   `<section id="tab-semantic" class="tab-section" role="tabpanel">` containing:
   - A severity filter `<select>` (All / High / Medium / Low)
   - A `<table id="semantic-table">` with thead: File, Severity, Category, Summary, Detail
   - `<tbody id="semantic-tbody">` and a `<div id="semantic-empty">` empty-state div
4. In the JS data-extraction block (line ~638), add:
   ```js
   var semanticFindings = D.semantic_findings || [];
   ```
5. Add a `buildSemanticAudit()` IIFE that:
   - Reads `semanticFindings`
   - Shows empty-state div if length is 0
   - Otherwise renders table rows using `textContent` (XSS-safe, matching existing pattern)
   - Applies severity colour via inline `style.color` using the existing CSS token values
   - Wires the severity filter `<select>` to re-render filtered rows
6. No new Chart.js chart is required for this tab (table only for Phase 1).

**Relevant Context:**
- Tab strip: `dashboard.html.j2` lines 489–495
- Contributors section ends at line ~480 (HTML) and JS block at line ~1042
- Existing `tdBadge()` helper at line ~680 can be reused for severity badges
- `--danger: #f87171`, `--warn: #fbbf24`, `--success: #86efac` are already defined

---

### Sub-Task 5 — Write pytest Coverage

**Status:** [ ] pending

**Intent:**
Add `tests/test_semantic.py` covering the new hybrid logic. Tests follow existing project
patterns: direct file I/O (no mocks library), `tmp_repo` fixture, helper functions, and
assertion messages.

**Expected Outcomes:**
- `test_top5_selection` — given a manifest with 7 Python files of varying complexity, verifies
  that `run_semantic_audit` produces exactly 5 findings (one per top file) and that the files
  selected match the 5 highest-complexity ones.
- `test_fewer_than_5_files` — given only 2 parseable files, verifies 2 findings are returned
  (no crash, no padding).
- `test_finding_structure` — verifies each returned `SemanticFinding` has non-empty `file`,
  `severity`, `category`, `summary`, `detail`, and `prompt_used` fields.
- `test_prompt_contains_source` — verifies the `prompt_used` field on a finding contains
  a substring from the actual source of the audited file (confirming `_build_prompt` reads
  the file).
- `test_orchestrator_semantic_flag` — runs `orchestrator.analyze(manifest, semantic=True)` on
  a small synthetic repo and asserts `result.semantic_findings` is a non-empty list of
  `SemanticFinding` instances.
- `test_renderer_includes_findings` — runs the full `render()` call on a result with
  `semantic_findings` populated, reads the HTML, and asserts that `"semantic_findings"` and at
  least one `summary` value appears in the output (confirming JSON embedding).

**Todo List:**
1. Create `tests/test_semantic.py`.
2. Import helpers from existing test files (`_write_py`, `_manifest_for`) by copying the
   pattern (do not import from sibling test files).
3. Implement the 6 test functions listed above.
4. No new test dependencies required — `pytest` + stdlib `re` + `json` are sufficient.

**Relevant Context:**
- `tests/test_analysis.py` — copy `_write_py`, `_manifest_for`, `_empty_result` helper patterns
- `tests/test_renderer.py` — HTML assertion pattern (write result → render → read HTML text → assert)
- `tests/conftest.py` — `tmp_repo` fixture available automatically

---

## Sub-Task Execution Order & Dependencies

```
Sub-Task 1 (models)          ← no dependencies; must complete first
       ↓
Sub-Tasks 2, 3, 4, 5         ← can be dispatched in parallel after Sub-Task 1
  (auditor) (orchestrator/CLI) (template) (tests)
```

Sub-Tasks 2–5 each depend only on Sub-Task 1 being complete. They have no inter-dependencies
and can be executed as four parallel subagent tasks.

---

## Acceptance Criteria

The Phase 1 build is complete when:
1. `pytest` passes with 0 failures across all 6 existing test files + `test_semantic.py`.
2. Running `code-compass analyze <repo> --semantic` produces an HTML file containing a
   "Semantic Audit" tab with one mock finding per top-5 file.
3. Running without `--semantic` produces identical output to the Phase 0 baseline
   (no regressions, `semantic_findings` serialised as `[]`).
4. No new `pip` dependencies are introduced.
