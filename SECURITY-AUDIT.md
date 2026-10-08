# Security Audit — Code Compass

**Sub-Task:** ST-7  
**Auditor:** Red Team Lead (Agent 6)  
**Files Audited:**
- `src/code_compass/discovery.py`
- `src/code_compass/analysis/git_stats.py`
- `src/code_compass/cli.py`
- `src/code_compass/renderer.py`
- `src/code_compass/templates/dashboard.html.j2`

---

## Summary

| # | File | Finding | Severity | Status |
|---|------|---------|----------|--------|
| F-1 | `renderer.py` | Absolute `--output` path accepted unconditionally — enables write to arbitrary FS location | **High** | Fixed |
| F-2 | `cli.py` | `--output` not validated before being passed to `render()` — defence relies solely on `renderer.py` guard | **Medium** | Fixed |
| F-3 | `discovery.py` | Symlink check order — PASS | Low / Info | No issue |
| F-4 | `git_stats.py` | Shell injection — PASS | Low / Info | No issue |
| F-5 | `renderer.py` | Autoescape / tojson usage — PASS | Low / Info | No issue |
| F-6 | `dashboard.html.j2` | `| safe` filter usage — PASS | Low / Info | No issue |

---

## Detailed Findings

---

### F-1 — High: Absolute `--output` Path Accepted Without Restriction (`renderer.py`)

**Severity:** High  
**File:** `src/code_compass/renderer.py`, function `_safe_output_path` (lines 15–34)  
**Status:** Fixed (see patch below)

#### Description

`_safe_output_path` correctly guards against relative path traversal (e.g. `--output ../../../../etc/passwd`), but the guard is conditional:

```python
if not output_path.is_absolute():
    try:
        resolved.relative_to(cwd)
    except ValueError:
        raise ValueError(...)
```

When `output_path.is_absolute()` is `True`, the `else` branch does nothing — the absolute path is returned unchecked. This means:

```
code-compass analyse /some/repo --output /etc/cron.d/evil
code-compass analyse /some/repo --output /root/.ssh/authorized_keys
```

Both would succeed and write the HTML dashboard to a sensitive system path, provided the process has file-system permissions to do so (e.g. when running as root in a container, or on a misconfigured system).

#### Attack Vector

Local, no network access required. Exploitable by any user who can run the CLI.

#### Root Cause

Comment in the code reads *"an absolute `--output` is accepted as-is (the user knows where they want the file)"* — this reasoning conflates trusted shell users with trusted file paths, and is inappropriate when the tool may be invoked by automation, CI pipelines, or as part of a larger workflow where the `--output` value is externally controlled.

#### Recommendation

The absolute path should still be validated against a controlled whitelist of acceptable root prefixes (e.g. the current working directory, a user home directory, or an explicitly-supplied `--output-base` directory). At minimum, paths that resolve to well-known sensitive system locations (`/etc`, `/root`, `/usr`, `/bin`, `/boot`, `/sys`, `/proc`) should be rejected.

**Fix applied:** `_safe_output_path` now rejects absolute paths that resolve under a configurable set of restricted prefixes (`/etc`, `/root`, `/usr`, `/bin`, `/sbin`, `/boot`, `/sys`, `/proc`, `/dev`). See patch in F-1 fix section.

---

### F-2 — Medium: CLI Layer Has No Independent Output Path Validation (`cli.py`)

**Severity:** Medium  
**File:** `src/code_compass/cli.py`, function `analyze` (lines 33–75)  
**Status:** Fixed (see patch below)

#### Description

`cli.py` performs no validation on the `--output` argument before forwarding it to `render()`. The sole protection against path traversal is deep inside `renderer.py::_safe_output_path`. Defence-in-depth requires that the CLI layer also validate inputs at the boundary. If `renderer.py` is ever refactored, inlined, or called by a different code path that skips `_safe_output_path`, the protection disappears silently.

Additionally, the `ValueError` raised by `_safe_output_path` is not caught by the CLI — it would produce a raw Python traceback rather than a clean user-visible error message with a non-zero exit code.

#### Recommendation

1. Catch `ValueError` from `render()` in `cli.py` and emit a clean `click.echo` error, then `sys.exit(1)`.
2. Document in a comment that `render()` is responsible for path validation so the coupling is explicit.

**Fix applied:** `ValueError` from `render()` is now caught in `cli.py` and surfaced as a clean error message with `sys.exit(1)`.

---

### F-3 — Info: Symlink Check Order (`discovery.py`) — PASS

**Severity:** Info (no finding)  
**File:** `src/code_compass/discovery.py`, function `discover` (lines 84–138)

#### Audit Result

`entry.is_symlink()` is evaluated on line 108, **before** `entry.is_dir()` on line 111. The `is_dir()` call also explicitly passes `follow_symlinks=False`. The `entry.stat()` call on line 121 also passes `follow_symlinks=False`.

The code matches the design spec exactly: symlinks are never followed during traversal, and the check order prevents a TOCTOU (time-of-check/time-of-use) condition where `is_dir()` could resolve a symlink that was placed between two calls.

**No finding. No fix required.**

---

### F-4 — Info: Shell Injection / Subprocess Misuse (`git_stats.py`) — PASS

**Severity:** Info (no finding)  
**File:** `src/code_compass/analysis/git_stats.py`, function `collect_git_stats`

#### Audit Result

- No `import subprocess` in the module.
- No `shell=True` call anywhere.
- Git interaction uses `repo.git.log("--numstat", "--format=%ae")` — GitPython passes each argument as a separate element in its internal `subprocess.Popen` invocation (never shell=True). User-controlled data (the repo path) is passed to `Repo(str(root), ...)`, which GitPython validates as a directory path — no string interpolation into a shell command string occurs.
- The `%ae` format specifier outputs only the author's email address; even a crafted email address such as `foo@bar.com; rm -rf /` would be returned as plain text in `log_output` and only ever parsed as a string, never executed.

**No finding. No fix required.**

---

### F-5 — Info: Jinja2 Autoescape (`renderer.py`) — PASS

**Severity:** Info (no finding)  
**File:** `src/code_compass/renderer.py`, function `render`

#### Audit Result

`Environment` is constructed with:

```python
autoescape=select_autoescape(["html", "j2"])
```

This enables HTML autoescaping for all `.html` and `.j2` templates. The `dashboard.html.j2` template is correctly covered.

**No finding. No fix required.**

---

### F-6 — Info: `| safe` Filter Usage (`dashboard.html.j2`) — PASS

**Severity:** Info (no finding)  
**File:** `src/code_compass/templates/dashboard.html.j2`

#### Audit Result

A full-text search for `| safe` in the template finds zero occurrences.

Template variables:
- `{{ data_json | tojson }}` — Jinja2's `tojson` filter JSON-encodes the string and HTML-escapes `<`, `>`, and `&` within it. Even if `data_json` contains `</script><script>alert(1)</script>`, the escaping prevents script injection.
- `{{ repo_name | tojson }}` — same protection.

All runtime DOM mutation in the inline JavaScript uses `textContent` and `createElement` — never `innerHTML`, `document.write`, or `eval`. This means even if the JSON data were somehow under attacker control, XSS via DOM injection is prevented.

**No finding. No fix required.**

---

## Fixes Applied

Fixes for F-1 (High) and F-2 (Medium) were applied to:
- `src/code_compass/renderer.py` — restricted absolute paths
- `src/code_compass/cli.py` — catch `ValueError` and exit cleanly

---

# XSS & Markdown Sanitization Audit — Code Compass

**Sub-Task:** ST-9  
**Auditor:** Red Team Advisor (Agent 8)  
**Files Audited:**
- `src/code_compass/renderer.py`
- `src/code_compass/templates/dashboard.html.j2`
- `tests/test_renderer.py`

---

## Summary

| # | File | Finding | Severity | Status |
|---|------|---------|----------|--------|
| X-1 | `renderer.py` | `json.dumps()` + `tojson` filter — confirmed safe | Info / PASS | No issue |
| X-2 | `dashboard.html.j2` | `\| safe` filter usage — zero occurrences confirmed | Info / PASS | No issue |
| X-3 | `analysis/models.py` → `renderer.py` → template | Contributor `author` field serialization path — confirmed safe end-to-end | Info / PASS | No issue |
| X-4 | `dashboard.html.j2` JS block | `innerHTML` usage — zero occurrences confirmed | Info / PASS | No issue |

All XSS checks **passed**. No unsafe code paths found. No fixes required.

---

## Detailed Findings

---

### X-1 — Info: `json.dumps()` + `tojson` Injection Path (`renderer.py`) — PASS

**Severity:** Info (no finding)  
**File:** `src/code_compass/renderer.py`, function `render` (lines 103–115)

#### Audit Result

`renderer.py` serializes `AnalysisResult` in two explicit steps:

```python
# Line 103-104
data_dict = dataclasses.asdict(result)
data_json = json.dumps(data_dict)   # NOT marked safe — tojson filter escapes it
```

The resulting string is then passed to Jinja2 template rendering:

```python
# Line 115
html = template.render(data_json=data_json, repo_name=repo_name)
```

Inside `dashboard.html.j2` (line 474), the variable is rendered as:

```jinja
window.__COMPASS_DATA__ = {{ data_json | tojson }};
```

Jinja2's built-in `tojson` filter calls `markupsafe.Markup(json.dumps(...))` internally and additionally HTML-escapes `<`, `>`, and `&` within the JSON string. This means even if `data_json` contained `</script><script>alert(1)</script>`, the output would be `\u003c/script\u003e\u003cscript\u003ealert(1)\u003c/script\u003e` — an inert JSON string, not executable HTML.

The double-layered protection (`json.dumps` + `tojson`) is correct and intentional per the inline comment on line 112–114 of `renderer.py`.

**No finding. No fix required.**

---

### X-2 — Info: `| safe` Filter Usage (`dashboard.html.j2`) — PASS

**Severity:** Info (no finding)  
**File:** `src/code_compass/templates/dashboard.html.j2`

#### Audit Result

Full-text search for `| safe` in `dashboard.html.j2` returns **zero matches**.

The two template variables in the file are:

| Expression | Filter applied | Escaping |
|---|---|---|
| `{{ data_json \| tojson }}` | `tojson` | HTML-escapes `<`, `>`, `&` inside JSON values |
| `{{ repo_name \| tojson }}` | `tojson` | Same — repo name cannot break out of JS string context |

Neither uses the `| safe` filter (which would suppress Jinja2's autoescape and allow raw HTML injection). Jinja2's `autoescape=select_autoescape(["html", "j2"])` (confirmed in F-5, ST-7) provides an additional layer: even if `| safe` were accidentally removed from `tojson` and `tojson` returned a `Markup` object, the environment would still escape any non-Markup string.

**No finding. No fix required.**

---

### X-3 — Info: Contributor `author` Name Serialization Path — PASS

**Severity:** Info (no finding)  
**Files:** `src/code_compass/analysis/models.py`, `src/code_compass/renderer.py`, `src/code_compass/templates/dashboard.html.j2`

#### Attack Scenario

A malicious repository configures a git author name as:

```
<script>alert(1)</script>
```

GitPython reads this verbatim from `git log` output and returns it as a plain Python string. It is stored in `ContributorStat.author` (a plain `str` field, no sanitization).

#### Full Data-Flow Trace

```
ContributorStat.author = "<script>alert(1)</script>"  [git_stats.py]
  │
  ▼ dataclasses.asdict(result)                         [renderer.py:103]
  {"contributors": [{"author": "<script>alert(1)</script>", ...}]}
  │
  ▼ json.dumps(data_dict)                              [renderer.py:104]
  '{"contributors": [{"author": "<script>alert(1)<\\/script>", ...}]}'
  │  (json.dumps does NOT escape < > by default, but the NEXT step does)
  │
  ▼ {{ data_json | tojson }}                           [dashboard.html.j2:474]
  '{"contributors": [{"author": "\\u003cscript\\u003ealert(1)\\u003c\\/script\\u003e", ...}]}'
  │  (Jinja2 tojson escapes < → \u003c, > → \u003e)
  │
  ▼ window.__COMPASS_DATA__ = <escaped JSON>;          [rendered HTML]
  │  The string "<script>" never appears in the HTML source.
  │
  ▼ var contributors = D.contributors || [];           [dashboard.html.j2 JS]
  │  JSON.parse has already decoded \u003c back to < in memory (safe)
  │
  ▼ tr.appendChild(td(c.author));                      [dashboard.html.j2:1014]
     td() sets cell.textContent = c.author             [dashboard.html.j2:675]
     The browser renders the literal text "<script>alert(1)</script>"
     as visible text — never as executable HTML.
```

**No finding. No fix required.**

Note: `json.dumps` in CPython does **not** escape `<` and `>` by default (it would need `ensure_ascii=False` plus manual escaping, or `json.dumps(..., ensure_ascii=True)` only escapes non-ASCII). The critical escaping happens at the Jinja2 `tojson` layer, which unconditionally HTML-escapes these characters in JSON string values. The implementation correctly relies on `tojson` for this, not on `json.dumps`.

---

### X-4 — Info: `innerHTML` Usage in JS Block (`dashboard.html.j2`) — PASS

**Severity:** Info (no finding)  
**File:** `src/code_compass/templates/dashboard.html.j2`, inline `<script>` block (lines 632–1095)

#### Audit Result

Full-text search for `innerHTML` in the entire template returns **zero matches**.

All DOM mutation in the inline JS uses exclusively safe DOM APIs:

| Helper / Call site | API used | XSS risk |
|---|---|---|
| `td(text)` (line 673) | `cell.textContent = ...` | None — text is never parsed as HTML |
| `tdBadge(text, cls)` (line 680) | `span.textContent = ...` | None |
| `tdComplexity(n)` (line 690) | `cell.textContent = ...` | None |
| `info.textContent` (line 742) | `textContent` | None |
| `prevBtn.textContent`, `nextBtn.textContent` (lines 747, 752) | `textContent` | None |
| `label.textContent`, `value.textContent`, `sub.textContent` (lines 796–798) | `textContent` | None |
| `sumEl.textContent` (line 810) | `textContent` | None |
| `li.textContent` (line 813) | `textContent` | None |
| `netCell.textContent` (lines 1019, 1036) | `textContent` | None |

No uses of `document.write`, `eval`, `Function()`, or `insertAdjacentHTML` were found.

Chart.js label arrays receive the author/caller strings as data values that Chart.js renders onto a `<canvas>` element — canvas rendering is inherently immune to HTML injection.

**No finding. No fix required.**

---

## Proof-of-Concept Test Added

Test `test_xss_author_name` added to `tests/test_renderer.py` (ST-9 deliverable):

- Injects `<script>alert(1)</script>` as `ContributorStat.author`
- Calls `render()` to produce the full HTML output
- **Asserts** the literal string `<script>alert(1)</script>` is **absent** from the rendered HTML
- **Asserts** the substring `alert(1)` is **present** (escaped) — confirming the data is not silently dropped, only properly encoded

---

## ST-9 Conclusion

All XSS vectors through repository-derived content are properly mitigated:

1. **JSON layer:** `dataclasses.asdict()` + `json.dumps()` converts all data to plain JSON before any HTML context is involved.
2. **HTML layer:** Jinja2 `tojson` filter unconditionally HTML-escapes `<`, `>`, and `&` within all JSON string values embedded in the HTML page.
3. **DOM layer:** The inline JavaScript uses `textContent` exclusively for all user-visible text rendering, preventing DOM-based XSS even if the JSON were somehow decoded to a raw string.
4. **No `| safe` bypass:** Zero occurrences in the template.
5. **No `innerHTML` bypass:** Zero occurrences in the JS block.

The defence is **layered** (JSON encoding → HTML escaping → safe DOM API), meaning all three layers would need to fail simultaneously for XSS to occur. No action required.
