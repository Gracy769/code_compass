# Plan: Modernize UI — Futuristic Cyberpunk/Glassmorphic Design

## Status
- [ ] Sub-task 1: Deep dark background + CSS design tokens
- [ ] Sub-task 2: Collapsible left sidebar navigation
- [ ] Sub-task 3: Top bar modernization
- [ ] Sub-task 4: Hero landing section (Overview tab)
- [ ] Sub-task 5: Mermaid diagram fixes
- [ ] Sub-task 6: Summary page data guard
- [ ] Validation

---

## Top-Level Overview

**Goal:** Modernize `src/code_compass/templates/dashboard.html.j2` to match the dark neon cyberpunk/glassmorphic mockup. The file is a single self-contained Jinja2 template that must emit a fully self-contained HTML file (zero external CSS/build steps). All CSS and JS stay inline.

**Scope:**
- Replace horizontal tab strip with a collapsible left sidebar.
- Add a Hero section at the top of the Overview tab.
- Update CSS design tokens to deep dark (#070b14) + cyan/blue glowing accents.
- Fix Mermaid SVG sizing so diagrams render at full height.
- Add `const DATA = typeof rawData === 'string' ? JSON.parse(rawData) : rawData;` guard in `summary.html.j2`.
- Preserve ALL existing tab content (System Prompt, Architecture, Call Graph, Contributors, Semantic Audit) and all Phase 1 fixes (350 KB cutoff, 10k symbol cap, 5k edge cap — these live in `analysis/` Python files, not touched here).

**Files changed:**
- `src/code_compass/templates/dashboard.html.j2` — primary target (1439 lines)
- `src/code_compass/templates/summary.html.j2` — minor data-guard addition only
- `src/code_compass/renderer.py` — no change needed (render context is already correct)
- `src/code_compass/analysis/tagger.py` — no change (Mermaid generator already uses `-->`)

---

## Sub-Task 1 — Deep Dark CSS Design Tokens

**Intent:** Update the global CSS `:root` variables and `body` background to match the deep dark cyberpunk palette from the mockup. This sets the foundation for every visual element.

**Expected Outcomes:**
- `body` background is `#070b14` (deepest dark) with a layered radial glow in cyan (#00b4d8) and blue (#3b82d4).
- CSS variables updated: `--bg-primary: #070b14`, `--accent-cyan: #00b4d8`, `--accent-blue: #3b82d4`, `--glow-cyan: rgba(0,180,216,0.25)`.
- Existing variable names (`--accent`, `--glass-bg`, etc.) kept where they are already correct to avoid breaking downstream uses.

**Todo List:**
1. In the `<style>` block, update `:root` — add `--bg-primary`, `--accent-cyan`, `--glow-cyan`, deepen `--glass-bg-nav` to `rgba(7, 11, 20, 0.92)`.
2. Update `body { background-color }` to `#070b14`.
3. Update `body { background-image }` radial gradients to use `#00b4d8` cyan glow at the top and a soft purple at the bottom-right (matching mockup ambient depth).

**Relevant Context:**
- CSS block: `dashboard.html.j2` lines 9–443 (the entire `<style>` tag).
- `:root` block: lines 16–51.
- `body` block: lines 53–65.

**Status:** [ ] pending

---

## Sub-Task 2 — Collapsible Left Sidebar Navigation

**Intent:** Replace the horizontal `.tab-strip` with a sleek collapsible left sidebar so all tabs are accessible from the left edge. The sidebar must be pure CSS+JS, no external dependencies. Collapsed state shrinks to 64px and shows icon-only with tooltips. Expanded state shows icon + label.

**Expected Outcomes:**
- A `<nav class="sidebar">` element is present, fixed to the left edge, full height.
- Expanded width: `220px`. Collapsed width: `64px`. Transition: smooth CSS width transition.
- Sidebar top: Code Compass logo + app name + collapse toggle button (`◀` / `▶`).
- Sidebar items: Overview, System Prompt, Architecture, Call Graph, Contributors, Semantic Audit — each with an SVG icon and a text label.
- Collapsed state: labels hidden, icons remain, hovering shows a tooltip (CSS `::after` pseudo-element or `title` attribute).
- Sidebar bottom: `[↗] Open Summary Explorer` link that calls `window.open(window.__SUMMARY_URL__, '_blank')`.
- Main content area (`#main-layout` wrapper) has `margin-left: 220px` (expanded) or `64px` (collapsed), with the same CSS transition.
- Old `.tab-strip` HTML and CSS removed.
- Tab routing JS updated: `document.querySelectorAll('.tab-btn')` → `document.querySelectorAll('.sidebar-nav-btn')`.
- Active sidebar item highlighted with cyan left-border + subtle glow.

**Todo List:**
1. Add sidebar CSS (`.sidebar`, `.sidebar.collapsed`, `.sidebar-logo`, `.sidebar-nav-btn`, `.sidebar-nav-btn.active`, `.sidebar-footer`, tooltip styles, `#main-layout`).
2. Replace `<div class="tab-strip">` HTML block (lines 480–487) with `<nav class="sidebar" id="sidebar">...</nav>`.
3. Wrap the existing `<header class="nav-bar">` + `<div class="tab-content">` in a `<div id="main-layout">`.
4. Update JS tab router to use `.sidebar-nav-btn` selector instead of `.tab-btn`.
5. Add JS for sidebar collapse toggle button.

**Relevant Context:**
- HTML: nav bar at lines 447–477, tab strip at lines 479–487, content container at lines 489–717.
- JS tab router: lines 890–912.
- The `data-tab` attribute must be preserved on sidebar buttons for the tab router to work.

**Status:** [ ] pending

---

## Sub-Task 3 — Top Bar Modernization

**Intent:** Update the top bar to match the clean minimal header from the mockup: `CODE COMPASS` brand in caps with compass icon, active repo badge, and right-aligned `Docs` and `GitHub` links.

**Expected Outcomes:**
- Brand text reads `CODE COMPASS` in letter-spaced caps.
- Repo badge shows `{{ repo_name }}` with a cyan glow border.
- Right side has plain text `Docs` link (points to `#`) and `GitHub` link (points to `https://github.com/{{ github_slug }}` when slug exists, else `https://github.com`).
- The existing `Sign in` / `Upload from GitHub` / `Local Folder` buttons are removed from the nav bar (they are relocated to the Hero section's action buttons).
- GitHub token modal and import modal HTML remain (they are triggered from the Hero section).

**Todo List:**
1. In `<header class="nav-bar">`, update `.nav-left`: change brand text to `CODE COMPASS`, update letter-spacing CSS.
2. Replace `.nav-actions` with just `Docs` + `GitHub` anchor links.
3. Update `.nav-bar` CSS: set `background: rgba(7,11,20,0.95)`, `border-bottom: 1px solid rgba(0,180,216,0.15)`.

**Relevant Context:**
- HTML: lines 447–477.
- Nav bar CSS: lines 67–138.

**Status:** [ ] pending

---

## Sub-Task 4 — Hero Landing Section (Overview Tab)

**Intent:** Insert a visually stunning hero section at the top of the Overview tab (`#tab-overview`). It must match the mockup exactly: left column with tagline, headline, input bar, dual action buttons, quick-launch chips; right column with status card, animated canvas network topology, and 3 metric cards.

**Expected Outcomes:**
- Hero section renders above the existing bento grid in `#tab-overview`.
- Left column:
  - Tagline `ARCHITECTURE, MADE VISIBLE` in small caps, cyan color, tracked.
  - Headline `Ingest any codebase.` + `<span>Surface invisible architecture.</span>` in #38bdf8.
  - Subtext paragraph.
  - Dark glass input bar with GitHub icon placeholder text.
  - `▶ Analyze Codebase` glowing blue gradient button.
  - `[GitHub Icon] Sign in with GitHub` button (same logic as existing `btn-gh-dynamic`).
  - Quick-launch chips: `transformers`, `fastapi`, `redis`.
- Right column:
  - `PARSING CODEBASE` status card with animated circular CSS spinner and animated cyan progress bar (animates to 100% on load).
  - Center `<canvas id="hero-topology-canvas">` — a pure-JS drawn isometric-style network of glowing nodes and edges using named hubs: `core`, `api`, `models`, `services`, `data`, `utils`. Rendered with `requestAnimationFrame` for a subtle float/pulse animation.
  - `CODEBASE MAP` mini overlay card with legend dots.
  - 3 glassmorphic metric cards: Files (from `D.files.length || totalFiles`), `0.75s AST`, `0 Panic`.
- The hero section has no Jinja2 logic — it is static HTML with JS-updated metric values.
- Below the hero, the existing stat cards (`#overview-cards`) and bento grid remain untouched.

**Todo List:**
1. Add hero CSS classes (`.hero-section`, `.hero-left`, `.hero-right`, `.hero-tagline`, `.hero-headline`, `.hero-input-bar`, `.hero-analyze-btn`, `.hero-github-btn`, `.hero-chip`, `.hero-status-card`, `.hero-metrics`, `.metric-glass-card`, `.hero-map-overlay`, `@keyframes progressFill`, `@keyframes spin`).
2. Insert the hero HTML block at the top of `<section id="tab-overview">`, before `<div class="stat-cards" id="overview-cards">`.
3. Re-wire the hero `Sign in with GitHub` button to call the same `btn-gh-dynamic` click handler logic (share the `updateGhButton()` function).
4. Add hero canvas drawing code in the JS IIFE: `drawHeroTopology()` function that uses Canvas 2D API to draw isometric-style layered hexagonal/blob layers with glowing node dots and connecting lines. Use `requestAnimationFrame` for a gentle pulsing animation.
5. Wire quick-launch chips to set the input value.
6. Animate the progress bar to 100% on load using `@keyframes`.
7. Update metric cards to use real data: Files = `totalFiles`, AST time = static `0.75s`, Panic = `0`.

**Relevant Context:**
- HTML insertion point: line 493, before `<div class="stat-cards" id="overview-cards">`.
- JS IIFE data variables (`totalFiles`, `symbols`, etc.) already computed at line 978–1017.
- Canvas API: no external dependencies needed.
- The hero must NOT break the existing `buildOverview()` IIFE, only precede it visually.

**Status:** [ ] pending

---

## Sub-Task 5 — Mermaid Diagram Fixes

**Intent:** Ensure the Architecture tab diagram never shrinks to a thin line and that `generate_mermaid_architecture()` correctly emits `-->` arrows.

**Expected Outcomes:**
- `_applySvgSize()` in the JS sets `minHeight: 520px` (main) and `360px` (overview) — already correct.
- The `.mermaid-container` CSS `min-height` is `520px` for main and `360px` for overview — already set.
- `generate_mermaid_architecture()` already uses `-->` arrow syntax (confirmed at tagger.py line 498).
- **No code change needed** for Mermaid arrow syntax.
- Adjust the main mermaid container min-height to `650px` (already at line 607 in the HTML).
- Ensure the SVG `width: 100%` is applied after render — already done in `_applySvgSize`.

**Todo List:**
1. Verify: open `tagger.py` line 498 — `-->` confirmed, no change required.
2. Verify: `_applySvgSize` at lines 1100–1107 sets `width:100%; minHeight:480–600px` — already correct.
3. No code changes required for this sub-task beyond what's done in the UI modernization pass.

**Relevant Context:**
- `tagger.py` lines 412–513.
- `dashboard.html.j2` lines 1100–1163.

**Status:** [ ] pending (verify only, no change expected)

---

## Sub-Task 6 — Summary Page Data Guard

**Intent:** Add the `const DATA = typeof rawData === 'string' ? JSON.parse(rawData) : rawData;` guard to `summary.html.j2` so the summary page correctly handles both string and object forms of the injected JSON data.

**Expected Outcomes:**
- In `summary.html.j2` JS, the data access pattern reads:
  ```js
  var rawData = window.__COMPASS_DATA__;
  var D = typeof rawData === 'string' ? JSON.parse(rawData) : (rawData || {});
  ```
- The existing data variables (`files`, `symbols`, etc.) derive from `D` without error.

**Todo List:**
1. Find the JS data-access block in `summary.html.j2`.
2. If the pattern `typeof rawData === 'string' ? JSON.parse(rawData)` is absent, add it.
3. If it already exists, mark sub-task complete.

**Relevant Context:**
- `summary.html.j2` — search for `window.__COMPASS_DATA__` to find the injection point.

**Status:** [ ] pending

---

## Validation

Run:
```
uv run code-compass analyze "C:\Users\Lenovo\Downloads\fastapi-master" --output "fastapi-dashboard.html"
```
Confirm:
- `fastapi-dashboard.html` opens in browser with the futuristic UI (dark background, glowing sidebar, hero section).
- `fastapi-dashboard-summary.html` opens and renders files/symbols with collapsible layer grouping.
- All 6 tabs are accessible from the sidebar and render their content.
- No JS console errors on first load.

---

## Implementation Notes

### Key constraint: Single self-contained HTML file
All CSS and JS must remain inline in the Jinja2 template. No `<link>` tags, no `import`, no build steps. External CDN scripts (`chart.js`, `mermaid`) are already present and acceptable (they were in the original).

### Layout structure after change
```
<body>
  <nav class="sidebar" id="sidebar">        ← NEW: replaces tab-strip
    [logo + collapse toggle]
    [nav items with data-tab attr]
    [footer: Open Summary Explorer]
  </nav>

  <div id="main-layout">                     ← NEW: wrapper for margin-left
    <header class="nav-bar">...</header>     ← MODIFIED: cleaner top bar
    <div class="tab-content">
      <section id="tab-overview">
        <div class="hero-section">...</div>  ← NEW: hero section
        <div class="stat-cards">...</div>    ← UNCHANGED
        <div class="bento-grid">...</div>    ← UNCHANGED
      </section>
      ... other tabs unchanged ...
    </div>
  </div>
</body>
```

### Hero canvas topology
The right-column canvas uses Canvas 2D API to draw an isometric-inspired layered network:
- 6 hub nodes in a roughly circular arrangement: `core` (center, larger), `api`, `models`, `services`, `data`, `utils`.
- Glowing lines between hubs (drawn with `createLinearGradient` or radial gradients).
- Subtle float animation using `Math.sin(Date.now() / 1500)` per node.
- Blue layered "platform" backgrounds drawn as tilted quadrilaterals to create the isometric effect from the mockup.
- No external libraries — pure Canvas 2D.

### Sidebar collapse behavior
- CSS transition on `width` with `overflow: hidden`.
- JS toggles a `.collapsed` class on `#sidebar` and `#main-layout`.
- `localStorage.getItem('cc_sidebar_collapsed')` persists state across page loads.
- In collapsed mode, `.sidebar-nav-label` has `opacity: 0; width: 0; overflow: hidden`.
- Tooltip on hover via CSS `position: relative` + `::after` pseudo or native `title` attribute.
