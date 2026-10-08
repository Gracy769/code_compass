# Phase 1: Code Compass Architecture Overhaul & Multi-Page Scaling Engine

## Overview

This plan overhauls Code Compass in four atomic steps:

1. **Backend Scalability & Clean Tagging** — prevent OOM on large repos, fix over-tagging, and update the renderer to emit two HTML files.
2. **Summary Explorer Template** — create `summary.html.j2`, a standalone multi-tab page for Files & Layers and Symbols.
3. **Main Dashboard Overhaul** — restructure tabs, replace GitHub auth buttons with a single dynamic button, add System Prompt tab, update Overview bento grid, and upgrade Call Graph to a two-panel explorer.
4. **Verification & Build** — run tests and generate real output to confirm both HTML files are correct.

**Codebase anchor points:**
- [`discovery.py`](src/code_compass/discovery.py) — `FileRecord`, `discover()`, `_DEFAULT_MAX_FILE_BYTES = 524_288`
- [`orchestrator.py`](src/code_compass/analysis/orchestrator.py) — `analyze()`, per-file loop (lines 30–62), `result.symbols`, `result.call_edges`
- [`tagger.py`](src/code_compass/analysis/tagger.py) — `extract_tags()` at line 291 (currently concatenates `content + file_path + symbol_names`)
- [`renderer.py`](src/code_compass/renderer.py) — `render()` at line 79 (single template, single output)
- [`templates/dashboard.html.j2`](src/code_compass/templates/dashboard.html.j2) — 7-tab layout; tabs: Overview, Architecture (Mermaid), Files & Layers, Symbols, Call Graph, Contributors (Top 100), Semantic Audit

---

## ST-1: Backend Scalability & Clean Tagging

**Status:** `[ ] pending`

### Intent
Prevent OOM crashes on massive repos (e.g. HuggingFace Transformers), cap unbounded symbol/edge lists, and eliminate AI-slop over-tagging caused by matching tags against folder names.

### Expected Outcomes
- Files > 350,000 bytes skip heavy AST parsing (skipped before entering the per-file parse loop).
- `result.symbols` is capped to 10,000 entries (sorted by `complexity` descending) after the main loop.
- `result.call_edges` is capped to 5,000 entries (sorted by caller frequency descending) after the main loop.
- Per-file analysis wrapped in `try/except MemoryError`; memory errors are recorded in `parse_errors` and the loop continues.
- `extract_tags()` in `tagger.py` no longer concatenates the `file_path` into the text search string; it only matches against `content` (actual source text) and `symbol_names`.

### Todo List
1. **`discovery.py`:** In `discover()`, change the `too_large` threshold constant from `_DEFAULT_MAX_FILE_BYTES` (512 KB) to `350_000` bytes. Specifically: add a new constant `_PARSE_SKIP_BYTES = 350_000` and use it to set `too_large = size > _PARSE_SKIP_BYTES` (the `max_file_bytes` parameter still controls binary-safe skipping, but parsing is now gated at 350 KB). **Alternatively** (simpler): set `_DEFAULT_MAX_FILE_BYTES = 350_000`.
   - _Decision needed:_ The simplest approach is to change the default constant. The existing field `too_large` in `FileRecord` already gates the parse loop at line 32 of `orchestrator.py`. Just lower the threshold.
2. **`orchestrator.py`:** Wrap the inner `analyze_python` / `analyze_js` call block in `try/except MemoryError` (separate from the existing bare `except Exception`) so memory errors are named explicitly and appended to `parse_errors`.
3. **`orchestrator.py`:** After the main `for record in manifest.files` loop (after line 62), add two cap operations:
   - Sort `result.symbols` by `complexity` descending, then slice to `[:10_000]`.
   - Build a caller-frequency map from `result.call_edges`, then sort edges by caller frequency descending and slice to `[:5_000]`.
4. **`tagger.py`:** In `extract_tags()` (line 296), change the `text` construction so that the `norm_path` (file path) is **not** included in the combined search string. The `text` variable should only include `content[:8192]` and the joined `symbol_names`. The file path is already used implicitly via language-extension tagging (lines 306–313), which is fine to keep.

### Relevant Context
- `FileRecord.too_large` at [`discovery.py:42`](src/code_compass/discovery.py:42) — already exists.
- `too_large` gate in orchestrator at [`orchestrator.py:32-33`](src/code_compass/analysis/orchestrator.py:32).
- `extract_tags` text construction at [`tagger.py:296`](src/code_compass/analysis/tagger.py:296): `text = (content[:8192] + " " + (norm_path) + " " + " ".join(symbol_names or [])).lower()`
- `_DEFAULT_MAX_FILE_BYTES = 524_288` at [`discovery.py:26`](src/code_compass/discovery.py:26).

---

## ST-2: Dual-File Renderer

**Status:** `[ ] pending`

### Intent
Update `render()` to always write a second companion HTML file (`[stem]-summary.html`) alongside the primary dashboard, and pass `summary_url` and `github_slug` into both template contexts so the dashboard can link to the summary and the summary can build GitHub file links.

### Expected Outcomes
- Calling `render(result, Path("fastapi-dashboard.html"))` writes both `fastapi-dashboard.html` (via `dashboard.html.j2`) and `fastapi-dashboard-summary.html` (via `summary.html.j2`).
- Both templates receive: `data_json`, `repo_name`, `summary_url` (e.g. `"fastapi-dashboard-summary.html"`), `github_slug` (e.g. `"fastapi/fastapi"` derived from `repo_name`, or empty string if unknown).
- The `github_slug` derivation is best-effort: split `repo_name` on `/` — if it has exactly two non-empty parts, use as-is; otherwise use empty string.
- The function signature is backward-compatible (no new required parameters).

### Todo List
1. In `renderer.py`, update `render()` to:
   a. Compute `summary_path = safe_path.parent / (safe_path.stem + "-summary.html")`.
   b. Derive `github_slug` from `repo_name` (best-effort, e.g. split by `/`; default `""`).
   c. Compute `summary_url = safe_path.stem + "-summary.html"`.
   d. Load both templates (`dashboard.html.j2` and `summary.html.j2`) from the same Jinja2 environment.
   e. Render dashboard with `data_json`, `repo_name`, `summary_url`, `github_slug`.
   f. Render summary with `data_json`, `repo_name`, `summary_url`, `github_slug`.
   g. Write both files.
   h. Return the primary (dashboard) path.
2. Return type and docstring remain unchanged.

### Relevant Context
- [`renderer.py:79`](src/code_compass/renderer.py:79) — current `render()` function.
- [`renderer.py:110`](src/code_compass/renderer.py:110) — `env.get_template("dashboard.html.j2")`.
- [`renderer.py:115`](src/code_compass/renderer.py:115) — `html = template.render(data_json=data_json, repo_name=repo_name)`.

---

## ST-3: Summary Explorer Template

**Status:** `[ ] pending`

### Intent
Create `src/code_compass/templates/summary.html.j2` — a standalone dark glassmorphic HTML page with two tabs: Files & Layers and Symbols. It links back to the dashboard and provides GitHub file links.

### Expected Outcomes
- File is created at [`src/code_compass/templates/summary.html.j2`](src/code_compass/templates/summary.html.j2).
- Page loads the same CSS design tokens as the dashboard (dark `#0b0f19` background, glassmorphic cards, same accent colors).
- Header contains: app logo, repo badge, `← Back to Dashboard` button (`onclick="window.close()"`).
- **Files & Layers tab:**
  - Text search + Layer dropdown + Ranking Tier dropdown filters.
  - When no search active, rows group by Layer with collapsible sticky headers showing `[▼] Layer Name (N files)`.
  - Columns: File Path (clickable GitHub link if `github_slug` is set, else plain text), Layer badge, Tier badge (no rank numbers), In/Out degree counts, up to 4 tag pills (each clickable to filter), Symbol count, Max Complexity (color-coded).
  - Pagination: 100 rows/page with `‹ Prev` / `Next ›` buttons.
- **Symbols tab:**
  - Text search + Kind dropdown + Layer dropdown.
  - Grouped by Layer by default; toggle button switches to group by Kind.
  - Columns: Symbol (bold), Kind (badge), Layer (badge), File (truncated with `title` tooltip), Line, Complexity, Tags.
  - Pagination: 100 rows/page.
- Data is loaded from the embedded `data_json` Jinja2 variable (same JSON blob as dashboard).
- All data manipulation is client-side JavaScript.

### Todo List
1. Create `src/code_compass/templates/summary.html.j2` with:
   a. `<!DOCTYPE html>` preamble, same `<head>` CSS design tokens as dashboard (copy `:root` variables, body gradient, card/badge/button styles).
   b. Header section: logo SVG, repo badge (`{{ repo_name }}`), `← Back` button.
   c. Tab strip with two buttons: `Files & Layers` and `Symbols`.
   d. Embedded JSON data: `<script>const DATA = {{ data_json | tojson }};</script>` — use the `tojson` filter for XSS safety (consistent with dashboard).
   e. Files & Layers tab panel with filters, grouped collapsible table, pagination.
   f. Symbols tab panel with filters, grouped table with toggle, pagination.
   g. JavaScript: parse `DATA`, implement filter/group/paginate logic, render both tabs.

### Relevant Context
- [`dashboard.html.j2:1-60`](src/code_compass/templates/dashboard.html.j2:1) — CSS design tokens to reuse.
- `data_json` variable contains `AnalysisResult` serialized via `dataclasses.asdict()` — keys are: `symbols` (list), `call_edges`, `contributors`, `parse_errors`, `dead_code`, `semantic_findings`, `files` (list of FileMetadata), `architecture_mermaid`, `ai_system_prompt`, `repo_stats`.
- `FileMetadata` fields: `path`, `language`, `size`, `complexity`, `symbols_count`, `layer`, `ranking_tier`, `rank_score`, `in_degree`, `out_degree`, `tags`, `rank`.
- `SymbolInfo` fields: `name`, `kind`, `file`, `line`, `complexity`, `tags`, `layer`, `rank_score`.
- GitHub link pattern: `https://github.com/{github_slug}/blob/master/{path}`.
- `github_slug` template variable passed from renderer (may be `""`).

---

## ST-4: Main Dashboard Overhaul

**Status:** `[ ] pending`

### Intent
Restructure the dashboard's tab bar, replace the dual GitHub auth buttons with a single dynamic Vercel-style button, update the Overview bento grid (remove AI prompt, add architecture matrix card with `Open Summary →`), add a dedicated System Prompt tab, and replace the static Call Graph chart with an interactive two-panel explorer. Also move Files & Layers and Symbols tabs out (they now live in the summary page).

### Expected Outcomes
- **Nav buttons:** Single dynamic button replacing `Sign in` + `Upload from GitHub`. State 1 (unauthenticated): shows `[GitHub icon] Sign in`; on click stores token in `localStorage('cc_gh_token')` and re-renders to State 2. State 2 (authenticated): shows `[Upload icon] Upload from GitHub`; on click opens a modal with search bar, recent repos list, `Import →` button. `Local Folder` button remains unchanged.
- **Tab order:** `Overview | System Prompt | Architecture (Mermaid) | Call Graph | Contributors (Top 100) | Semantic Audit` (6 tabs — `Files & Layers` and `Symbols` removed).
- **Overview bento grid:** AI Prompt box is removed. In its place: a `Repository Architecture Matrix & Summary` card showing layer breakdown counts, dominant ecosystem, symbol density, and an `Open Summary →` button (`window.open(summary_url, '_blank')`). Health Scorecard and Architecture Topology Preview remain.
- **System Prompt tab:** Full-width `<pre>` block with `ai_system_prompt` content, scrollable. Top-right `Copy Full AI Prompt` button with toast notification.
- **Call Graph tab:** Two-panel layout — Left (40%): searchable list of top callers by degree; Right (60%): callee breakdown for selected symbol (callee name, file location, layer badge).
- **Overflow safeguards:** All section cards get `overflow-x: auto`. Tables get `table-layout: fixed; width: 100%`. Long file paths truncated with CSS ellipsis and `title` tooltip. No horizontal overflow at 1280px.

### Todo List
1. **Tab bar restructure:** In the `<div class="tab-strip">` block (lines 482–493), remove `Files & Layers` and `Symbols` tab buttons and add `System Prompt` tab between `Overview` and `Architecture (Mermaid)`.
2. **Nav button:** Replace the two buttons (`btn-signin-gh` and `btn-import-gh`) with a single `<button id="btn-gh-dynamic">` that toggles state based on `localStorage('cc_gh_token')`. Keep `btn-upload-local` and hidden file input unchanged.
3. **GitHub import modal:** Add a hidden modal `<div id="github-import-modal">` with search input, results list container, and `Import →` button. Wire open/close logic in JavaScript.
4. **Overview tab — bento grid:** Remove the `bento-col-8` AI Architecture Prompt card. Add a `bento-col-8` "Repository Architecture Matrix & Summary" card that reads from `DATA.repo_stats` and `DATA.files` for layer counts, computes dominant ecosystem from `DATA.symbols`, renders a mini stats table, and includes an `Open Summary →` button using `summary_url`.
5. **System Prompt tab section:** Add `<section id="tab-prompt">` containing a full-width card with a `<pre id="ai-prompt-text">` block and `Copy Full AI Prompt` button with toast logic.
6. **Call Graph tab:** Replace the `<canvas id="callgraph-chart">` with a two-panel div layout. Left panel: search input + scrollable list of `<div class="caller-row">` entries. Right panel: header (selected caller name) + table of callees (callee name, file, layer badge). Wire click-to-select logic in JavaScript.
7. **Overflow safeguards:** Add `overflow-x: auto` to `.section-card` CSS. Add `table-layout: fixed; width: 100%` to relevant tables. Add `max-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap` to file path cells with `title` attribute set via JS.
8. **JavaScript:** Update `initOverview()`, add `initCallGraph()`, add `initSystemPrompt()`, update tab-init dispatch to register the new System Prompt tab, remove init calls for `Files & Layers` and `Symbols` tabs (those now live in summary.html.j2).

### Relevant Context
- Tab strip at [`dashboard.html.j2:482-493`](src/code_compass/templates/dashboard.html.j2:482).
- Nav buttons at [`dashboard.html.j2:455-478`](src/code_compass/templates/dashboard.html.j2:455).
- Overview bento at [`dashboard.html.j2:503-568`](src/code_compass/templates/dashboard.html.j2:503).
- AI Prompt card at [`dashboard.html.j2:535-551`](src/code_compass/templates/dashboard.html.j2:535) — this card is removed from Overview and moved to its own tab.
- Call Graph tab section starts around line 683 (single `<canvas>`).
- Template variable `summary_url` passed from renderer; used in `Open Summary →` button.

---

## ST-5: Verification & Build

**Status:** `[ ] pending`

### Intent
Confirm all backend changes are test-safe and produce working dual-file HTML output for a real repository.

### Expected Outcomes
- `uv run --extra test pytest` passes with zero regressions.
- `uv run code-compass analyze "C:\Users\Lenovo\Downloads\fastapi-master" --output "fastapi-dashboard.html"` completes without OOM.
- Both `fastapi-dashboard.html` and `fastapi-dashboard-summary.html` are written to disk.
- Opening `fastapi-dashboard.html` in a browser: `Open Summary →` button correctly opens `fastapi-dashboard-summary.html` in a new tab.
- Summary page shows two tabs with populated, paginated data tables.

### Todo List
1. Run `uv run --extra test pytest` and confirm zero failures.
2. Run the analyze CLI command against the fastapi-master directory.
3. Visually verify both HTML files exist and the cross-link is correct (grep for `summary_url` value in the rendered HTML).
4. If any test breaks, fix the root cause before marking complete.

### Relevant Context
- CLI entry point at [`src/code_compass/cli.py`](src/code_compass/cli.py) — calls `discover()`, `analyze()`, `render()`.
- Tests are in [`tests/`](tests/) directory.

---

## Implementation Order

```
ST-1 (discovery + orchestrator + tagger backend fixes)
  → ST-2 (renderer dual-file output)
    → ST-3 (summary.html.j2 new file)
      → ST-4 (dashboard.html.j2 overhaul)
        → ST-5 (test + build verification)
```

Each step depends on the previous being complete. ST-3 and ST-4 both consume the `data_json` / `summary_url` / `github_slug` contract established in ST-2.
