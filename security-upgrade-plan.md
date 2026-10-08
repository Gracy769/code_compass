## FOOLPROOF AUDIT — What this plan does NOT do (destructive rules excluded)

| Rule / Pattern | Status in this plan | Evidence |
|---|---|---|
| `overflow:hidden` globally on `html`/`body` | NOT PROPOSED — never mentioned | Confirmed: no CSS change proposed |
| `.lenis-smooth` injection | NOT PROPOSED — irrelevant | Confirmed: no Lenis in repo |
| `data-lenis-prevent` modification | NOT PROPOSED — irrelevant | Confirmed |
| Removal of existing `new Lenis(...)` init | NOT PROPOSED — irrelevant | Confirmed |
| Overwrite `lenis-plan.md` / rename | NOT PROPOSED | Confirmed |
| Delete `STORAGE_DIR` / session folders | NOT PROPOSED — kept intact | Confirmed: session isolation preserved |
| Remove `tokenModal` HTML (`line 776`) | NOT PROPOSED — can stay or hide; no removal required | Confirmed |
| Change `dashboard.html.j2` / `summary.html.j2` CSS globally | NOT PROPOSED — only defensive JS/header/template guards added, no CSS removal | Confirmed |
| Modify `simulator.py` / unrelated Python sources | NOT PROPOSED — only targeted security files (`security.py`, `app.py`, `cli.py`, `cache_manager.py` if added) | Confirmed |
| Apply destructive command (delete file, overwrite without backup) | NOT PROPOSED — all steps are additive (insert, guard, header, file) | Confirmed |
| Break cookie-only session if Plan 2 auth not active | EXCLUDED — steps 4 and 6 explicitly require Plan 2 auth first; standalone steps 1,2,3,5,7,8,9 do not touch session mechanism | Confirmed |

---

# CONTEXT — The 9 security gaps (verified evidence, brief only)

Verified from `security.py`, `app.py`, `cli.py`, `SECURITY-AUDIT.md`, `Dockerfile`, `pyproject.toml`:

1. Rate limit: only concurrent semaphore (`line 112`: 429 when 2 slots busy); no per-IP/user sequential limit.
2. Token in body: `app.py:894-906` (`githubToken` variable) -> `line 922` (`"token": token` in JSON body); not `Authorization: Bearer` header.
3. No CSP: `app.py` has zero `Content-Security` lines.
4. No CSRF: cookie-only (`samesite=strict` at `line 1053`); no token mechanism for state-changing POST (`/analyze`, `/repos`).
5. URL cap: `repoUrlInput` (`line 656`) has regex (`canonical_github_url`) but no `len() <= 500`; long URLs = DoS.
6. Cookie identity: `line 1049` regex `[A-Za-z0-9_-]{43}` only; no account binding; cookie stolen (XSS from #3) = full access.
7. Subprocess: `line 89` (`subprocess.run(command, ...)`) uses list (good) but `work_dir` validated only implicitly; needs `resolve()` + `relative_to`.
8. Audit/logging: no persistent file for failed auth/ZIP errors; attacker probes silently.
9. ZIP/fork bomb (`new` — user-requested): `security.py` checks `.git/config` include and file count/size but does NOT detect nested `.zip` (fork) or extreme compression ratio (zip bomb); no sequential-upload termination.

---

# IMPLEMENTATION STEPS — All 9 (defensive, non-disruptive, ordered)

Order rule: steps 1,2,3,5,7,8,9 are standalone (safe anytime). Steps 4 and 6 require Plan 2 auth (`supabase-plan.md`) to be active first; they are excluded from standalone execution and flagged.

---

## STEP 1 — Rate limit (standalone; safe; low disruption)

Target file: `src/code_compass/web/app.py` (insertion only).
Evidence: `line 112` (`raise HTTPException(status_code=429, ...)`) — only concurrent slot guard; no per-IP/user sequential guard.

What to do (additive, no removal):
- Before `/analyze` endpoint (`line` near analysis execution): add a simple per-source rate check.
- Method (defensive, does not break existing semaphore):
  - Read `request.client.host` (IP) or session cookie identity.
  - Maintain an in-memory or file-based counter: `last_request_time`, `count_in_window` (60-second window).
  - If count > 10 within 60 seconds: return `HTTPException(status_code=429, detail="Rate limit exceeded.")`.
- Why non-disruptive: concurrent semaphore (`line 112`) remains; this is an additional sequential guard. If user hits concurrent limit, original 429 remains; sequential guard only blocks rapid repeats.
- What NOT to do (excluded): do NOT remove `JOB_SLOTS` semaphore; do NOT change `MAX_CLONE_SECONDS`.

---

## STEP 2 — Token in body -> Authorization header (standalone; safe; low disruption)

Target files: `src/code_compass/web/app.py` (`line 676-680` button, `894-906` JS variable, `922` JSON body).
Evidence: `line 894`: `githubToken = null`; `line 906`: `githubToken = val || null`; `line 922`: `token: token` inside `JSON.stringify({ url: ..., token })`; no `Authorization` header usage.

What to do (additive/replacement of transmission method only):
- Client (`line 894-906`): keep `githubToken` variable; change submission mechanism.
- Instead of putting `token` into JSON body (`line 922`), add header to fetch/request:
  - `headers: { "Content-Type": "application/json", "Authorization": "Bearer " + githubToken }`
- Server (`line 922` and endpoint handler): instead of reading `req.token` (body field), read from header:
  - `token = (request.headers.get("authorization") or "").replace("Bearer ", "").strip()`
  - Pass this to `_run_worker()` / `run_analysis()` same as before (`line 85`: `if token: env[...]`).
- Why non-disruptive: the same `token` value reaches `env["CODE_COMPASS_CLONE_TOKEN"]` (`line 85-86`); only the transport layer changes (body -> header). Client UI (`line 676`) unchanged; modal (`line 776`) unchanged.
- What NOT to do: do NOT delete `githubToken` variable from JS; do NOT change `tokenModal` HTML; do NOT modify `security.py` validation rules.

---

## STEP 3 — CSP header (standalone; safe; low disruption)

Target file: `src/code_compass/web/app.py` (add header to response; no template edit).
Evidence: zero `Content-Security` lines in `app.py`; landing HTML (`LANDING_HTML`) embeds JS (`line` near landing start) but has no CSP.

What to do (additive header only):
- Add middleware or per-endpoint response header in `app.py`:
  - `response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self' https://api.github.com; img-src 'self' data:; font-src 'self';"`
  - Note: `'unsafe-inline'` for `style-src` is required because landing CSS is inline; do NOT remove inline CSS (would break design). `script-src 'self'` allows embedded landing JS; if external CDN scripts added later, expand.
- Why non-disruptive: no `dashboard.html.j2`, `summary.html.j2`, or landing HTML content changed; only the HTTP response header added. Existing `tojson` (`line 1263`) works under `script-src 'self'`.
- What NOT to do: do NOT inject meta tag into HTML; do NOT restrict `connect-src` to exclude `https://api.github.com` (needed for GitHub auth/repo picker in Plan 2); do NOT set `default-src 'none'` (would break all resources).

---

## STEP 4 — CSRF token (REQUIRES Plan 2 auth active; medium disruption; phase with Plan 2)

Target files: `src/code_compass/web/app.py` (`line 26-34` session, endpoint), `security.py` (optional token validation), `supabase-plan.md` (Plan 2 auth).
Evidence: cookie-only (`line 1049`: regex); `samesite=strict` (`line 1053`); `POST /analyze` and new `/repos` (Plan 2) are state-changing; no CSRF mechanism.

What to do (only if `supabase-plan.md` Plan 2 auth implemented first — `SIGN IN WITH GITHUB` active):
- After Supabase Auth session established (`line` session mechanism updated in Plan 2 Step 2.4):
  - Generate a CSRF token: `csrf_token = secrets.token_urlsafe(32)`; store in session (cookie or Supabase user metadata or server-side session store).
  - Client: include `X-CSRF-Token` header in `POST` requests (`/analyze`, `/repos`).
  - Server: verify `request.headers.get("X-CSRF-Token") == session_csrf`; reject with 403 if mismatch.
- Alternative (double-submit cookie): set cookie `csrf_token` = random; require same value in body/header. Does not require server-side session store.
- Why non-disruptive only with Plan 2: cookie-only session (`line 1049`) has no identity to bind CSRF to; adding CSRF without user identity creates false security (attacker steals cookie = passes CSRF). Once Plan 2 binds session to `user.id`, CSRF token is meaningful.
- What NOT to do: do NOT add CSRF without Plan 2 auth; do NOT remove existing session cookie mechanism (`line 1049`) during this step.

---

## STEP 5 — URL length cap (standalone; safe; low disruption)

Target file: `src/code_compass/web/app.py` (`line 1068`: `canonical_github_url(req.url)`); `security.py` (`canonical_github_url()` function).
Evidence: regex validates format but no `len()` check; very long URL strings = DoS or buffer issues.

What to do (additive check):
- Before regex (`security.py` or `app.py` call site):
  - `if len(url) > 500: raise ValueError("URL exceeds maximum length.")`
- This applies to both `canonical_github_url()` input and `repoUrlInput` (`line 656`).
- Why non-disruptive: existing valid URLs (`https://github.com/owner/repo`) are well under 500 chars; only malicious/extreme inputs blocked.
- What NOT to do: do NOT change regex rules in `canonical_github_url`; do NOT change `repoUrlInput` placeholder text.

---

## STEP 6 — Cookie identity binding (REQUIRES Plan 2 auth active; medium-high disruption; phase with Plan 2)

Target files: `app.py` (`line 1049` cookie regex, `line 1051-1053` cookie settings, `line 79` session binding), `supabase-plan.md` (Plan 2 auth user identity).
Evidence: cookie regex only (`[A-Za-z0-9_-]{43}`); no `user.id` binding; cookie stolen (XSS from missing CSP in #3) = full session access.

What to do (only after Plan 2 auth active — `signInWithGitHub()` returns valid session with `user.id`):
- Replace or augment session cookie mechanism:
  - Option A (minimal): keep cookie (`SESSION_COOKIE`) but add `user_id` claim to cookie data (signed/encrypted with server secret). Verify `user_id` matches Supabase user from JWT on each request (`line 26`: `_session()` enhanced).
  - Option B (recommended): bind `work_dir / "owner"` (`line 79`) to `user.id` from Supabase Auth; `check_run_owner()` (`security.py`) verifies both cookie validity AND `user.id` presence; reject if cookie has no user binding.
- Rotate cookie on auth state change: when user signs out or session expires (`max_age=86400` at `line 1053`), regenerate cookie; old cookie invalid (no user binding).
- Why non-disruptive with Plan 2: cookie mechanism (`line 1049`) stays; only enhanced with identity check. Without Plan 2, doing this alone breaks cookie-only users because no `user.id` exists.
- What NOT to do: do NOT delete cookie mechanism before Plan 2 active; do NOT change cookie name or regex unexpectedly.

---

## STEP 7 — Subprocess guard (standalone; safe; low disruption)

Target file: `src/code_compass/web/app.py` (`line 89`: `subprocess.run(command, ...)`), `security.py` (`extract_zip_safely()`).
Evidence: command uses list (`sys.executable, "-m", ...`) which prevents shell injection, but `work_dir` and `source` passed to command are not explicitly validated with `resolve()` + `relative_to()` before execution.

What to do (defensive guard, no logic change):
- Before `_run_worker()` call (`line 83-89`):
  - `work_dir_path = Path(str(work_dir)).resolve()`
  - Confirm `work_dir_path.is_relative_to(STORAGE_DIR.resolve())` (or designated safe base); if not, raise `ValueError`.
  - Confirm `work_dir_path.exists()` and is directory; confirm `source` (repo URL / ZIP path) resolves to allowed root (repo path or upload directory).
- Confirm `command` list never constructed from unsanitized user input; `name` and other args come from validated fields.
- Why non-disruptive: defensive check only; does not change analysis execution (`discover()`, `run_analysis()`), output, or session behavior.
- What NOT to do: do NOT change command structure to use `shell=True`; do NOT remove existing `env` variables (`CODE_COMPASS_CLONE_TOKEN` at `line 85-86`).

---

## STEP 8 — Audit logging (standalone; safe; low disruption)

Target: new file or existing log mechanism (no source file removed/edited except insertion of log calls).
Evidence: `security.py` raises `ValueError` for unsafe ZIPs; `cli.py` records `parse_errors` (`line` after analysis) but does not persist failed auth/ZIP attempts.

What to do (additive file creation):
- Create `security_audit.log` (or `audit.log`) in persistent directory (not `STORAGE_DIR` temp; separate from session folders).
- Log events (structured format, e.g., JSON line):
  - `timestamp`, `event_type` (`failed_auth`, `invalid_zip`, `path_traversal_attempt`, `parse_error`, `rate_limit_block`), `source_ip` (`request.client.host` if available), `details` (file/hash/repo slug, no secrets).
- Insertion points (additive only):
  - `security.py`: after `raise ValueError(...)` for ZIP errors — log event.
  - `app.py`: after `check_run_owner()` failure (`line 1130`, `1173`, `1190`) — log `failed_auth`.
  - `cli.py`: after `parse_errors` recorded — log `parse_error`.
  - Rate limit (`Step 1`): after 429 response — log `rate_limit_block`.
- Why non-disruptive: log file separate; no endpoint, session, or analysis flow changed; secrets (`token` values from `line 922`) never logged (only event type and source identifier).
- What NOT to do: do NOT log `githubToken`, `api_key`, `session_cookie_value`; do NOT replace existing `parse_errors` behavior (`cli.py`).

---

## STEP 9 — ZIP/fork bomb detection (new — user-requested; standalone; safe; low disruption)

Target file: `src/code_compass/web/security.py` (`extract_zip_safely()` loop); `app.py` (sequential upload termination logic).
Evidence: current checks (`line 71-72` `S_IFMT`, `line 61` `.git/config`) cover path traversal and special files but NOT nested archives or extreme compression ratios; `STORAGE_DIR` (`line 43-45`) provides session isolation but not sequential-upload termination.

What to do (defensive additions inside existing loop):
- A. Nested archive detection (`security.py`, inside `for member in members` loop):
  - After `name = member.filename.replace(...)`: check if `name.lower().endswith(".zip")`.
  - If true: `raise ValueError("ZIP contains nested archive (potential zip/fork bomb).")`
  - Why safe: only blocks `.zip` members; does not affect normal file uploads.
- B. Compression ratio / zip bomb detection (`security.py`, inside loop):
  - Read `member.file_size` (uncompressed) and `member.compress_size` (compressed; available via `zf.getinfo(member.filename).compress_size` or `member.compress_size` if ZipInfo provides it).
  - If `member.file_size > 0` and `compress_size / file_size < 0.01` (i.e., >100:1 compression): `raise ValueError("ZIP member exceeds safe compression ratio (potential zip bomb).")`
  - Note: Python `zipfile` `member.file_size` is uncompressed; `compress_size` is compressed size. Ratio check is approximate; if exact value unavailable, use `file_size > 10 * member.file_size` as heuristic (but exact ratio preferred).
- C. Sequential upload termination (`app.py`, before `run_analysis()` / before `_bounded_worker()`):
  - Check session/IP recent upload count (use same mechanism as Step 1 rate limit but for upload events specifically): if `upload_count_in_30s >= 2` (2-3 back-to-back): `raise HTTPException(status_code=429, detail="Sequential upload limit exceeded.")`
  - Terminate process/session: call `cleanup_expired_runs()` or delete current `work_dir` if sequential uploads exceed limit.
- D. Nested depth guard (optional, defensive): after extracting ZIP contents to `work_dir`, scan `work_dir` for any `.zip` files; if found, delete `work_dir` and return error. Prevents post-extraction nested archive execution.
- Why non-disruptive: additions inside existing loops and endpoint checks; no removal of `STORAGE_DIR`, session cookie (`line 1051`), or analysis flow; no change to `discover()` or `run_analysis()` logic.
- What NOT to do: do NOT remove `STORAGE_DIR`; do NOT disable ZIP upload feature; do NOT change `MAX_UPLOAD_BYTES` without adding new guard; do NOT delete existing session folders on every request.

---

# CROSS-REFERENCE — How steps interact with existing plans/files

| Step | File changed | Interaction with Plan 1 (Cache) | Interaction with Plan 2 (Auth) | Interaction with existing security |
|---|---|---|---|---|
| 1 Rate limit | `app.py` insertion | Independent — cache read/write continues | Independent — auth session separate | Keeps `line 112` semaphore; adds sequential guard |
| 2 Token header | `app.py` insertion (`line 894-922`) | Independent — token transport only | Independent — auth uses Supabase JWT; this is GitHub private repo token | Keeps `env["CODE_COMPASS_CLONE_TOKEN"]` (`line 85-86`); changes transport layer |
| 3 CSP header | `app.py` header insertion | Independent — header only | Required for XSS defense (protects `user.id` from injection) | Defends `line 1263-1266` (`tojson`) and landing HTML |
| 4 CSRF token | `app.py` + `security.py` insertion | Independent | **Requires Plan 2 active** — CSRF meaningless without user identity binding | Keeps `SESSION_COOKIE` (`line 1049`); adds token verification |
| 5 URL cap | `security.py` + `app.py` insertion | Independent | Independent | Keeps `canonical_github_url()` (`security.py`); adds length guard |
| 6 Cookie identity | `app.py` session mechanism | Independent (optional `user_id` in cache table) | **Requires Plan 2 active** — binds session to `user.id` | Keeps cookie mechanism (`line 1051-1053`); enhances `check_run_owner()` (`security.py`) |
| 7 Subprocess guard | `app.py` insertion (`line 89` area) | Independent | Independent | Keeps `subprocess.run()` list form; adds `resolve()` + `relative_to()` validation |
| 8 Audit logging | New file (`security_audit.log`) + `security.py`/`app.py` insertion | Optional `user_id` reference in log | Optional user identity log | Keeps `parse_errors` (`cli.py`); adds persistent audit file |
| 9 ZIP/fork bomb | `security.py` insertion + `app.py` insertion | Independent — protects analysis of malicious uploads | Independent — malicious ZIP may try to steal session via XSS; CSP (#3) + identity (#6) defend | Keeps all existing ZIP limits (`MAX_*`); adds nested/compression/sequential guards |

