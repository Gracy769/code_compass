# Security Hardening Implementation Plan

## Top-Level Overview

**Goal:** Implement 9 security defences identified in `security-upgrade-plan.md` against the live codebase.  
**Scope:** `src/code_compass/web/app.py` and `src/code_compass/web/security.py` — strictly additive changes only.  
**Non-goals:** No CSS changes, no deletion of session directories, no modifications to unrelated analysis logic, no touch of `worker.py`, `discovery.py`, or dashboard templates.  
**Constraint:** Steps 4 (CSRF) and 6 (Cookie Identity Binding) from the original plan require Supabase auth (Plan 2). The task description requires executing them as standalone double-submit CSRF cookie protection (Step 4) and cookie hardening (Step 6), which are both achievable without Supabase. We implement them in this restricted form.

---

## Sub-Task 1 — Per-IP Sequential Rate Limiter

**Status:** `[ ] pending`

**Intent:** Add an in-memory windowed rate limiter that allows a maximum of 10 requests per 60-second rolling window per client IP. This is separate from and complementary to the existing `JOB_SLOTS` concurrent semaphore at line 47 of `app.py`.

**Expected Outcomes:**
- A module-level `dict` tracks `(ip → list[timestamps])` of recent POST requests.
- Any IP exceeding 10 requests in the last 60 seconds gets `HTTPException(429, "Rate limit exceeded. Try again later.")`.
- The existing `JOB_SLOTS` semaphore is untouched.
- When a rate-limit block fires, it is logged to the audit log (see Sub-Task 8).

**Todo List:**
1. After the `JOB_SLOTS` line (line 47 in `app.py`), add a module-level `_RATE_LIMIT: dict[str, list[float]] = {}` and constants `_RL_WINDOW = 60` and `_RL_MAX = 10`.
2. Write a helper function `_check_rate_limit(ip: str) -> None` that prunes timestamps older than `_RL_WINDOW`, appends `time.time()`, and raises `HTTPException(429, ...)` if count exceeds `_RL_MAX`.
3. Call `_check_rate_limit(request.client.host)` at the top of `analyze_git_repo` and `analyze_zip_upload` endpoints, before any other processing.

**Relevant Context:**
- `app.py` line 47: `JOB_SLOTS = asyncio.Semaphore(2)` — keep this.
- `app.py` line 1211: `analyze_git_repo` — insertion point.
- `app.py` line 1267: `analyze_zip_upload` — insertion point.

---

## Sub-Task 2 — Token Header Transport

**Status:** `[ ] pending`

**Intent:** Move the GitHub PAT from the JSON body (`"token": token`) to the `Authorization: Bearer` header, both on the client side (embedded JS in `LANDING_HTML`) and server side (endpoint handler). This prevents tokens from appearing in server-side request body logs.

**Expected Outcomes:**
- Client JS `startAnalysis()` sends `Authorization: Bearer <token>` header instead of `token` in JSON body.
- `GitAnalyzeRequest` Pydantic model's `token` field is no longer used/read for the private-repo token.
- `analyze_git_repo` extracts the token from `request.headers.get("authorization")` and passes it to `_bounded_worker`.
- The `githubToken` JS variable and token modal HTML remain unchanged.

**Todo List:**
1. In `LANDING_HTML` JS (around line 967-971): change the `fetch('/api/analyze-git', ...)` call to pass `Authorization: Bearer ${token || ''}` in the headers object and remove `token` from the JSON body. Keep `token` as `null` safe (do not send `"Bearer null"`).
2. In `analyze_git_repo` (line 1241): replace `token=req.token or ""` with `token = (request.headers.get("authorization") or "").replace("Bearer ", "").strip()` and pass that variable.
3. The `token` field on `GitAnalyzeRequest` can remain (backwards compat, just ignored server-side). Do not delete the Pydantic model field.

**Relevant Context:**
- `app.py` line 938: `let githubToken = null;`
- `app.py` line 967-971: `fetch('/api/analyze-git', { ... body: JSON.stringify({ url, strict, semantic, token }) })`
- `app.py` line 1241: `token=req.token or ""`

---

## Sub-Task 3 — Content-Security-Policy Header

**Status:** `[ ] pending`

**Intent:** Add a `Content-Security-Policy` response header to every HTML response. This constrains what scripts, styles, and connections the browser allows, defending against XSS. Inline styles and inline Supabase JS CDN must stay allowed.

**Expected Outcomes:**
- All HTML responses (`/`, `/dashboard/{id}`, `/summary/{id}`) include a `Content-Security-Policy` header.
- Inline `<style>` and `<script>` in the landing page continue to work (`'unsafe-inline'`).
- The Supabase JS CDN (`cdn.jsdelivr.net`) is allowed in `script-src`.
- GitHub API calls from `connect-src` work.
- No template HTML is changed.

**Todo List:**
1. Add a `@app.middleware("http")` function at module level in `app.py` (after the `app = FastAPI(...)` declaration) that injects the CSP header into every response where `Content-Type` includes `text/html`. Use:
   ```
   default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; connect-src 'self' https://api.github.com; img-src 'self' data: https:; font-src 'self';
   ```
2. No changes to HTML templates or inline CSS/JS.

**Relevant Context:**
- `app.py` line 38-42: `app = FastAPI(...)` — middleware must be added after this.
- `app.py` line 1117: Supabase CDN import — `https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/+esm`.

---

## Sub-Task 4 — CSRF Double-Submit Cookie Protection

**Status:** `[ ] pending`

**Intent:** Implement stateless double-submit CSRF cookie protection for the state-changing POST endpoints (`/api/analyze-git`, `/api/analyze-upload`). A random token is set in a `csrf_token` cookie; the client echoes it back in the `X-CSRF-Token` request header; the server validates they match.

**Expected Outcomes:**
- The `/` homepage response sets a `csrf_token` cookie (`SameSite=Strict`, `HttpOnly=False` so JS can read it, `Secure` on non-localhost).
- Client JS reads `csrf_token` from `document.cookie` and includes it as `X-CSRF-Token` header on all POST requests (`/api/analyze-git` and `/api/analyze-upload`).
- Server extracts `X-CSRF-Token` header and `csrf_token` cookie; if they don't match, raises `HTTPException(403, "CSRF token mismatch.")`.
- CSRF mismatch events are logged to the audit log.

**Todo List:**
1. In `homepage()` route (line 1134), set a second cookie `csrf_token = secrets.token_urlsafe(32)` alongside the session cookie (set whenever missing or invalid, using `httponly=False` so JS can read it).
2. Write a `_check_csrf(request: Request) -> None` helper that compares `request.headers.get("x-csrf-token")` against `request.cookies.get("csrf_token")`. Raise `HTTPException(403, "CSRF token mismatch.")` on mismatch.
3. Call `_check_csrf(request)` at the start of `analyze_git_repo` and `analyze_zip_upload`.
4. In JS (`startAnalysis` and the upload handler), add a helper `getCsrfToken()` that reads the cookie and includes it as `X-CSRF-Token` in the fetch headers.

**Relevant Context:**
- `app.py` line 1134-1144: `homepage()` route with `set_cookie` — add second cookie here.
- `app.py` line 967-971: `fetch('/api/analyze-git', ...)` — add X-CSRF-Token header.
- `app.py` line 1003-1007: `fetch('/api/analyze-upload', ...)` — add X-CSRF-Token header.

---

## Sub-Task 5 — URL Length Hard Cap

**Status:** `[ ] pending`

**Intent:** Add a simple length guard before `canonical_github_url()` is called, blocking pathologically long URL strings that could cause DoS via regex backtracking or large memory allocations.

**Expected Outcomes:**
- If `len(url) > 500`, `canonical_github_url()` raises `ValueError("URL exceeds maximum length of 500 characters.")` immediately, before any regex runs.
- All valid GitHub repo URLs (max ~60 chars) are unaffected.

**Todo List:**
1. In `security.py`, at the very start of `canonical_github_url(value: str)` (line 26), add: `if not value or len(value) > 500: raise ValueError("URL exceeds maximum length of 500 characters.")`.

**Relevant Context:**
- `security.py` line 24-45: `canonical_github_url()`.

---

## Sub-Task 6 — Session Cookie Hardening

**Status:** `[ ] pending`

**Intent:** Ensure the session cookie is always set with the full set of hardening attributes. The current code already uses `httponly=True`, `samesite="strict"`, `max_age=86400`, and conditional `secure`. This step confirms/enforces those settings are correct and adds rotation on regeneration to prevent session fixation.

**Expected Outcomes:**
- Session cookie always has `httponly=True`, `samesite="strict"`, `max_age=86400`.
- `secure` follows existing logic: `True` for non-localhost, `False` for localhost (no change needed).
- Session cookie is regenerated (new value) if the existing one is invalid — already done. Confirm there's no path that re-uses a stale cookie value.
- Document that session rotation is implicit: a new `secrets.token_urlsafe(32)` is generated when the cookie is missing/invalid.

**Todo List:**
1. Review `homepage()` (line 1139-1143) — verify all hardening attributes are present. No code change needed if already correct (they are).
2. Add an explicit `max_age=86400` confirmation (it's already at 24 * 60 * 60). If there are any other `set_cookie` calls (e.g. `sb_session` at line 1180), verify they also have appropriate `httponly` and `samesite`.
3. If the `sb_session` cookie at line 1180 is missing `httponly=True`, add it (it already has `httponly=True, samesite="strict", max_age=3600`).
4. This sub-task is primarily a verification + documentation step; make only the minimum correction needed.

**Relevant Context:**
- `app.py` line 1139-1143: `response.set_cookie(SESSION_COOKIE, ...)` — already correct.
- `app.py` line 1180: `response.set_cookie("sb_session", ...)` — already has `httponly=True, samesite="strict"`.

---

## Sub-Task 7 — Subprocess Path Guard

**Status:** `[ ] pending`

**Intent:** Before the subprocess call in `_run_worker`, resolve `work_dir` to its canonical path and confirm it is a subdirectory of `STORAGE_DIR`. This prevents directory traversal attacks where a crafted path might escape the temp directory.

**Expected Outcomes:**
- `_run_worker` resolves `work_dir` with `.resolve()` and asserts it is relative to `STORAGE_DIR.resolve()`.
- If the check fails, raises `ValueError("Invalid work directory path traversal.")` (caught and turned into a 500 by the endpoint).
- The existing `subprocess.run(command, ...)` list form and all env var passing remain unchanged.

**Todo List:**
1. In `_run_worker` (line 84), at the top of the function body, add:
   ```python
   work_dir_path = Path(str(work_dir)).resolve()
   if not work_dir_path.is_relative_to(STORAGE_DIR.resolve()) or not work_dir_path.is_dir():
       raise ValueError("Invalid work directory path traversal.")
   ```
2. No changes to the `command` list construction or subprocess call.

**Relevant Context:**
- `app.py` line 84-107: `_run_worker()` function.
- `app.py` line 44: `STORAGE_DIR` definition.

---

## Sub-Task 8 — Persistent Security Audit Logger

**Status:** `[ ] pending`

**Intent:** Create a lightweight structured-JSON audit logger that writes security events to `security_audit.log` in the project's working directory (not inside `STORAGE_DIR`). Log only event metadata — never tokens, API keys, or cookie values.

**Expected Outcomes:**
- `security.py` exports a `log_security_event(event: str, client_ip: str, details: str) -> None` function.
- Log file is `security_audit.log` in the process working directory (or alongside `app.py`).
- Log format: one JSON object per line: `{"timestamp": "...", "event": "...", "client_ip": "...", "details": "..."}`.
- Events logged:
  - `rate_limit_block` — from Sub-Task 1's rate limiter.
  - `invalid_zip` — when `extract_zip_safely()` raises `ValueError`.
  - `path_traversal_attempt` — when path traversal guard fires (Sub-Task 7).
  - `failed_auth` — when `check_run_owner()` returns `False` in dashboard/summary/audit endpoints.
  - `csrf_mismatch` — when Sub-Task 4's CSRF check fails.

**Todo List:**
1. In `security.py`, add `import json` and `import datetime` at the top.
2. Add `AUDIT_LOG_PATH = Path(__file__).parent.parent.parent / "security_audit.log"` constant. (This places it at the project root, outside temp storage.)
3. Write `log_security_event(event: str, client_ip: str = "", details: str = "") -> None` that appends one JSON line to `AUDIT_LOG_PATH`. Use `try/except` so logging never breaks the main request flow.
4. Export `log_security_event` from `security.py`.
5. In `app.py`, import `log_security_event` from `code_compass.web.security`.
6. Call it at each event site: rate limiter, CSRF mismatch, path traversal, failed auth (in `check_run_owner` failure branches in dashboard/summary/audit endpoints), and ZIP errors (wrap the `_bounded_worker("zip", ...)` call's `ValueError` path).

**Relevant Context:**
- `security.py` line 1-12: existing imports.
- `app.py` line 30-36: existing imports from `security`.
- `app.py` line 1342-1374: dashboard/summary routes where `check_run_owner` failures happen.

---

## Sub-Task 9 — ZIP / Fork-Bomb & Archive Guards

**Status:** `[ ] pending`

**Intent:** Extend `extract_zip_safely()` with two new guards: (a) reject any member ending in `.zip` to block nested archives; (b) reject members with extreme compression ratio (>100:1) to block classic zip-bomb payloads. Additionally, track upload attempts per IP and reject if >2 within 30 seconds.

**Expected Outcomes:**
- Any `.zip` member inside an archive raises `ValueError("ZIP contains nested archive (potential zip bomb).")`.
- Any member where `file_size > 100_000` AND `compress_size / file_size < 0.01` raises `ValueError("Excessive compression ratio detected (potential zip bomb).")`.
- A client IP that attempts more than 2 archive uploads within 30 seconds gets `HTTPException(429, ...)` and the current `work_dir` is cleaned up.
- Existing ZIP limits (`MAX_ZIP_FILES`, `MAX_ZIP_MEMBER_BYTES`, `MAX_EXTRACTED_BYTES`) are unchanged.

**Todo List:**
1. In `security.py`, inside `extract_zip_safely()` in the `for member in members` loop (after the `name =` line), add:
   - Nested ZIP guard: `if name.lower().endswith(".zip"): raise ValueError("ZIP contains nested archive (potential zip bomb).")`
   - Compression ratio guard: after the `count` and `total` increments, check `member.file_size > 100_000 and member.compress_size > 0 and member.compress_size / member.file_size < 0.01` → raise `ValueError("Excessive compression ratio detected (potential zip bomb).")`.
2. In `app.py`, add module-level `_UPLOAD_RATE: dict[str, list[float]] = {}` and a `_check_upload_rate(ip: str) -> None` helper (window=30s, max=2).
3. At the start of `analyze_zip_upload`, call `_check_upload_rate(request.client.host)`. On rejection, clean up any partial work dir and log the event.
4. Add tests in `tests/test_web_security.py` for nested ZIP rejection and compression ratio rejection.

**Relevant Context:**
- `security.py` line 57-91: `extract_zip_safely()` loop body.
- `app.py` line 1267-1298: `analyze_zip_upload`.
- `tests/test_web_security.py`: existing ZIP tests to use as pattern reference.

---

## Verification

After all sub-tasks are complete:
1. Run `uv run --extra test pytest` — all existing tests must pass; new tests for Sub-Task 9 guards must pass.
2. Confirm `security_audit.log` is created and that each event type can be triggered.
3. Confirm no dashboard/summary HTML visual changes occurred (no CSS was modified).
