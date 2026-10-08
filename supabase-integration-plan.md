# Supabase Caching & GitHub OAuth Integration Plan

## Overview

Add opt-in Supabase caching and GitHub OAuth to Code Compass without breaking anything.

**Goal:** When `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` env vars are present, expensive analysis
results are cached in a Supabase `analysis_cache` table and served back in <1 s on repeat visits.
When those env vars are absent the app continues to work exactly as before — zero crashes, zero
behavioural changes.

**GitHub OAuth** is surfaced as an optional convenience in the web UI: a "Sign in with GitHub"
button is added to the landing page `<script>` block; when Supabase is not configured the button
is hidden and the existing manual-PAT token modal remains the only path.

**Constraints:**
- Do NOT reformat or alter templates (`dashboard.html.j2`, `mindmap.js.j2`, `summary.html.j2`).
- Do NOT alter `renderer.py`, `tagger.py`, `git_stats.py`, or any analyzer module.
- All Supabase calls are wrapped in `try/except` — any Supabase error is a cache miss, never a crash.
- All existing `pytest` tests must remain green.

---

## Sub-Tasks

---

### ST-1 · Add dependency and schema artefact

**Status:** [ ] pending

**Intent:**  
Add `supabase>=2.0` to the project's dependency list and create a companion SQL schema file that
documents the `analysis_cache` table shape. Neither change modifies any runtime Python logic.

**Expected Outcomes:**
- `pyproject.toml` lists `supabase>=2.0` (and `postgrest` is pulled in transitively by the
  supabase SDK; no explicit `postgrest` line needed unless the supabase package omits it).
- `src/code_compass/schema.sql` exists and describes `analysis_cache` with all required columns.
- All existing tests still pass (`pytest`).

**Todo List:**
1. In `pyproject.toml` → `[project] dependencies` array, append `"supabase>=2.0"` after the last
   existing dependency (do not remove any existing entry).
2. Create `src/code_compass/schema.sql` with a `CREATE TABLE IF NOT EXISTS analysis_cache` block
   covering: `repo_hash varchar PRIMARY KEY`, `repo_name varchar NOT NULL DEFAULT ''`,
   `github_slug varchar`, `analysis_json jsonb NOT NULL`, `dash_path varchar`,
   `summary_path varchar`, `created_at timestamptz NOT NULL DEFAULT now()`,
   `expires_at timestamptz NOT NULL`.

**Relevant Context:**
- `pyproject.toml` line 12–22: existing dependency block — append to it.
- No other file needs to change in this sub-task.

---

### ST-2 · Create `cache_manager.py`

**Status:** [ ] pending

**Intent:**  
New module `src/code_compass/cache_manager.py` that owns all Supabase interaction. It initialises
the Supabase client lazily from env vars, and exposes three public functions:
`compute_hash`, `load_cache`, `save_cache`. Everything is wrapped defensively so that any
configuration problem or network error degrades to a cache miss rather than a crash.

**Expected Outcomes:**
- File `src/code_compass/cache_manager.py` exists.
- `compute_hash("path")` returns a stable 32-character hex string.
- `load_cache` returns `None` when Supabase is unconfigured.
- `load_cache` returns `None` when the row is absent or expired.
- `load_cache` returns a reconstructed `AnalysisResult` dataclass when a valid row is found.
- `save_cache` returns `False` silently when Supabase is unconfigured.
- `save_cache` upserts a row and returns `True` on success.
- All behaviour falls back gracefully on any `Exception`.

**Todo List:**
1. Create `src/code_compass/cache_manager.py`.
2. At module top, attempt `from supabase import create_client, Client` inside a `try/except
   ImportError` — if import fails, set a sentinel so all public functions become no-ops.
3. Initialise `_client: Client | None = None` at module scope. Write a private `_get_client()`
   helper that reads `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` from `os.environ`, calls
   `create_client(url, key)` once (cache in module-level var), and returns `None` if either var is
   absent or if creation raises.
4. Implement `compute_hash(repo_path_or_url: str, github_ref: str = "") -> str`:
   - `hashlib.sha256(f"{repo_path_or_url}:{github_ref}".encode()).hexdigest()[:32]`
5. Implement `load_cache(hash_str: str, ttl_days: int = 7) -> AnalysisResult | None`:
   - Call `_get_client()`; if `None`, return `None`.
   - Query: `.table("analysis_cache").select("analysis_json").eq("repo_hash", hash_str).gt("expires_at", datetime.now(UTC).isoformat()).maybe_single().execute()`
   - If response data is `None` / empty, return `None`.
   - Deserialize `analysis_json` and reconstruct `AnalysisResult` via a helper that converts
     nested dicts back to nested dataclasses (use `dacite` or a manual recursive approach —
     manual is safer given the project has no dacite dep; use `AnalysisResult(**data)` with nested
     list comprehensions for `SymbolInfo`, `CallEdge`, etc.).
   - Wrap everything in `try/except Exception`; return `None` on any error.
6. Implement `save_cache(hash_str: str, result: AnalysisResult, ttl_days: int = 7, repo_name: str = "", github_slug: str = "") -> bool`:
   - Call `_get_client()`; if `None`, return `False`.
   - `payload = dataclasses.asdict(result)` → JSON-encode via `json.dumps`.
   - Build row dict with `repo_hash`, `repo_name`, `github_slug`, `analysis_json` (as the parsed
     dict, not a string — Supabase jsonb column accepts a dict), `created_at`, `expires_at`.
   - `.table("analysis_cache").upsert(row).execute()`.
   - Return `True` on success, `False` on any `Exception`.

**Relevant Context:**
- `AnalysisResult` and all nested dataclasses live in `src/code_compass/analysis/models.py`.
- `dataclasses.asdict` is already used in `renderer.py` for the same serialization purpose.
- The nested dataclasses to reconstruct: `SymbolInfo`, `CallEdge`, `ContributorStat`,
  `SemanticFinding`, `FileMetadata` (all fields are primitives/lists-of-primitives).

---

### ST-3 · Surgical insertion into `cli.py`

**Status:** [ ] pending

**Intent:**  
Add cache-check-before-analysis and cache-save-after-render to the `analyze` command. The existing
commit-SHA lookup (`repo_ref`) already exists at line 95–99; the hash can be computed from
`repo_path_or_url=str(repo)` and `github_ref=repo_ref`.

**Expected Outcomes:**
- Running `code-compass analyze <repo>` on a cached repo prints
  `[code-compass] Loaded analysis from Supabase cache!` and skips `discover` / `run_analysis`.
- After rendering, the result is saved to Supabase (silently if unconfigured).
- All CLI flags (`--output`, `--strict`, `--semantic`) still work.
- The existing code path (no Supabase) is completely unchanged in behaviour.

**Todo List:**
1. Add imports at top of `cli.py`:
   ```python
   from code_compass.cache_manager import compute_hash, load_cache, save_cache
   ```
2. In the `analyze` function, insert cache-check logic immediately before line 53
   (`manifest = discover(repo)`):
   - Get `repo_ref` early (move the existing `try/except git Repo` block from inside the
     render try-block to before the cache check, so the hash can include the commit SHA).
   - `hash_str = compute_hash(str(repo), repo_ref)`
   - `cached = load_cache(hash_str, ttl_days=30)`
   - If `cached is not None`:
     - `click.echo("[code-compass] Loaded analysis from Supabase cache!")`
     - `result = cached`
     - Jump directly to the render step (use an `else` block wrapping `discover + run_analysis`).
3. After the existing `render(...)` call, add:
   ```python
   slug = detect_github_slug(repo)   # already in scope
   save_cache(hash_str, result, ttl_days=30, repo_name=repo.name, github_slug=slug or "")
   ```
   This must be inside the existing `try/except ValueError` block but after `render(...)`.

**Relevant Context:**
- `cli.py` is 119 lines. The `analyze` function spans lines 41–107.
- Current `repo_ref` assignment is at lines 95–99, inside the render try-block.
- `detect_github_slug` is already imported and used at line 86.
- Guard: `save_cache` must only be called when `hash_str` is defined (i.e., not if early-exit
  from a cache hit skipped the hash computation — actually hash is computed before the branch,
  so it is always defined).

---

### ST-4 · Surgical insertion into `web/app.py`

**Status:** [ ] pending

**Intent:**  
Add cache-hit fast-path to `analyze_git_repo`, save to cache after successful worker run, add
`/auth/callback` route for Supabase GitHub OAuth, and add the GitHub OAuth JS + repo picker
modal to the `LANDING_HTML` script block. Everything is guarded behind Supabase availability.

**Expected Outcomes:**
- A repeated `/api/analyze-git` call for the same repo+ref returns a `dashboard_url` immediately
  from cache instead of cloning.
- After a successful analysis the result is saved to cache.
- `/auth/callback?code=...` exchanges the OAuth code with Supabase and sets a session cookie.
- The landing page shows a "Sign in with GitHub" button **only** when `SUPABASE_URL` is set
  (detected via JS fetch to `/api/supabase-config`). When not set, nothing changes.
- The existing token modal and direct URL input remain fully functional.

**Todo List:**
1. Add imports to `app.py` (top, after existing imports):
   ```python
   from code_compass.cache_manager import compute_hash, load_cache, save_cache
   ```
2. Add a new route `GET /api/supabase-config` that returns
   `{"enabled": True/False, "supabase_url": url_or_empty, "anon_key": anon_key_or_empty}` —
   reading `SUPABASE_URL` and `SUPABASE_ANON_KEY` from env (anon key is for browser-side OAuth,
   distinct from the service key used server-side). This route lets the JS decide whether to show
   the OAuth button without embedding secrets in HTML.
3. In `analyze_git_repo` (line 1076), after `repo_url = canonical_github_url(req.url)` and before
   `run_id, work_dir = _new_run(request)`:
   - Compute `hash_str = compute_hash(repo_url)` (no git ref available before clone; use URL
     only).
   - `cached = load_cache(hash_str, ttl_days=7)` — note: since we have no commit SHA pre-clone,
     cache key is URL-only; this is a reasonable tradeoff (TTL 7 days).
   - If `cached is not None`: synthesise a unique `run_id`, write the cached `analysis_json` to
     a temp work dir, call `render(...)` to produce the HTML, and return `dashboard_url`. The
     run must still be session-owned (set owner file). This allows `/dashboard/<run_id>` to serve
     the page normally.
4. After the successful `_bounded_worker` call in `analyze_git_repo`, attempt to read
   `work_dir / "analysis.json"` (written by the worker), reconstruct `AnalysisResult`, and call
   `save_cache(hash_str, result, ttl_days=7)`. Wrap in `try/except` — failure must not raise.
5. Add route `GET /auth/callback`:
   - Read `code` query param; if absent raise 400.
   - Exchange code with Supabase using the server-side client.
   - On success, set a session cookie (e.g. `sb_session`) and redirect to `/`.
   - Wrap all Supabase calls in `try/except`; on failure redirect to `/?auth_error=1`.
6. In `LANDING_HTML`, within the `<script>` block (after the existing `resetState` function,
   before `</script>`), add:
   - A `signInWithGitHub()` JS function that calls `fetch('/api/supabase-config')`, and if
     `enabled`, uses Supabase JS SDK (loaded from CDN via a dynamic `<script>` tag or `import()`)
     to call `supabase.auth.signInWithOAuth({provider: 'github'})`.
   - A `fetchUserRepos()` function that calls `/api/repos` (added in step 7) and populates a
     repo picker modal.
   - On page load, call `fetch('/api/supabase-config')` to conditionally reveal the
     "Sign in with GitHub" button (the button itself is added to the HTML in the nav area,
     hidden by default via `display:none`, revealed only when `enabled` is true).
   - Add a minimal repo-picker modal `<div>` in the HTML body (hidden by default).
7. Add route `GET /api/repos`:
   - Reads the Supabase session token from the cookie `sb_session`.
   - Queries the GitHub API `/user/repos` using the OAuth access token stored in the Supabase
     session.
   - Returns JSON list of `{name, full_name, url}`.
   - If no session or Supabase unconfigured, return `{"repos": [], "authenticated": false}`.

**Relevant Context:**
- `analyze_git_repo` spans lines 1076–1097.
- The worker writes `work_dir / "analysis.json"` and `work_dir / "dashboard.html"` (confirmed
  from the `view_dashboard` route which reads `run_dir / "dashboard.html"`).
- `LANDING_HTML` ends at line 1053 (`"""`). The `<script>` block is lines 827–1050.
- The nav `<nav>` block (lines 155–199 of LANDING_HTML) is where the GitHub sign-in button
  should be added — as a new `<button>` with `id="githubSignInBtn" style="display:none"`.
- Do NOT remove or alter the existing token modal HTML (lines 809–820) or existing JS functions
  (`openTokenModal`, `closeTokenModal`, `saveToken`, `startAnalysis`, `uploadZip`, etc.).
- `SUPABASE_ANON_KEY` env var (distinct from `SUPABASE_SERVICE_KEY`) is the public browser key;
  it must not appear hardcoded in HTML.

---

### ST-5 · Tests for `cache_manager.py`

**Status:** [ ] pending

**Intent:**  
Provide a `tests/test_cache_manager.py` that verifies the three behaviours mandated by the spec
without requiring a live Supabase instance. Use `unittest.mock` / `pytest monkeypatch` in the
established project style.

**Expected Outcomes:**
- `test_hash_stability`: same inputs always produce the same 32-character hex string.
- `test_hash_length`: result is exactly 32 chars and hex.
- `test_load_cache_no_supabase_url`: when `SUPABASE_URL` is empty/unset, `load_cache` returns
  `None` and does not raise.
- `test_save_cache_no_supabase_url`: when `SUPABASE_URL` is empty/unset, `save_cache` returns
  `False` and does not raise.
- `test_load_cache_hit`: mock the Supabase client to return a fabricated row; verify that
  `load_cache` returns an `AnalysisResult` with the correct fields.
- `test_load_cache_miss`: mock client returns `None` data; verify `load_cache` returns `None`.
- `test_save_cache_success`: mock client `.upsert().execute()` succeeds; verify return is `True`.
- `test_save_cache_error`: mock client raises; verify return is `False`.
- All 8 tests run with `pytest` and the whole existing suite remains green.

**Todo List:**
1. Create `tests/test_cache_manager.py`.
2. Use `monkeypatch.setenv` / `monkeypatch.delenv` to control `SUPABASE_URL` and
   `SUPABASE_SERVICE_KEY`.
3. Use `unittest.mock.MagicMock` to fabricate the Supabase client and chain
   `.table().select().eq().gt().maybe_single().execute()` return values.
4. Monkeypatch `code_compass.cache_manager._get_client` to inject the mock client where needed.
5. For `test_load_cache_hit`, build a minimal `analysis_json` dict matching the `AnalysisResult`
   dataclass shape (all list fields empty, `architecture_mermaid=""`, etc.) and verify the
   returned object is an `AnalysisResult` instance.

**Relevant Context:**
- `tests/conftest.py` uses `tmp_path` fixture from pytest; same style is expected here.
- `AnalysisResult` fields are all `list[SomeDataclass]` or `str`/`dict` — straightforward to
  fabricate minimal instances.
- `cache_manager._get_client` must be monkeypatch-able (module-level function, not a class).
- Module-level `_client` cached var must be reset between tests; simplest approach is to
  monkeypatch `_get_client` directly rather than patching the module-level `_client`.

---

## Implementation Order

```
ST-1  →  ST-2  →  ST-3  →  ST-4  →  ST-5
```

ST-1 and ST-2 have no dependencies on each other and can be done in either order, but ST-2 must
precede ST-3 and ST-4. ST-5 depends on ST-2.

## Risk Notes

- **Worker output format**: ST-4 step 4 assumes `work_dir/analysis.json` is written by the
  worker. Verify this in `src/code_compass/web/worker.py` before implementing ST-4. If the file
  name differs, adjust accordingly.
- **AnalysisResult reconstruction**: `dataclasses.asdict` produces nested plain dicts. The
  `load_cache` reconstruction must convert them back to dataclass instances. Manual nested
  constructors are safest (no extra dep). If any field is a `Path`, it will be serialised as a
  string — the models use `str` for file paths already so this is fine.
- **Supabase JS SDK**: for the OAuth button, load Supabase JS from CDN only after confirming
  `enabled=true` from `/api/supabase-config` to avoid 404-loading CDN script on self-hosted
  installs. Use `<script type="module">` with dynamic import from the Supabase CDN ESM URL.
- **Circular import risk**: `cache_manager.py` imports from `analysis.models`; `cli.py` already
  imports from `analysis`; no circular risk exists.
