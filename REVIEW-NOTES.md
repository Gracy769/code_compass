# Backend Code Review — ST-4 Findings

**Reviewer:** Agent 2 (Backend Reviewer — paranoia-driven pair programmer)  
**Files reviewed:**
- `src/code_compass/discovery.py`
- `src/code_compass/analysis/orchestrator.py`
- `src/code_compass/analysis/python_analyzer.py`
- `src/code_compass/analysis/js_analyzer.py`
- `src/code_compass/analysis/git_stats.py`

---

## Summary

| ID | File | Finding | Severity | Status |
|---|---|---|---|---|
| R-01 | `git_stats.py` | `Repo` object not closed via context manager — subprocess handle leak | **Blocking** | ✅ Fixed |
| R-02 | `js_analyzer.py` | Duplicate `CallEdge` entries for calls inside functions | **Blocking** | ✅ Fixed |
| R-03 | `discovery.py` | `os.scandir` — verified iterative, no full list materialisation | Non-Blocking (pass) | — |
| R-04 | `discovery.py` | Symlink guard order — `is_symlink()` checked before `is_dir()` | Non-Blocking (pass) | — |
| R-05 | `discovery.py` | `_is_binary` — file handle closed via `with` block | Non-Blocking (pass) | — |
| R-06 | `orchestrator.py` | No file contents retained after per-file parse; no redundant accumulator | Non-Blocking (pass) | — |
| R-07 | `python_analyzer.py` | AST not stored on `AnalysisResult`; only extracted primitives returned | Non-Blocking (pass) | — |
| R-08 | `js_analyzer.py` | Parser/Language objects are module-level singletons | Non-Blocking (pass) | — |
| R-09 | `js_analyzer.py` | `Parser` singletons not thread-safe; concurrent parse will corrupt state | Non-Blocking (risk) | — |
| R-10 | `python_analyzer.py` | `source` string (up to 512 KB) lives for duration of function call | Non-Blocking (unavoidable) | — |

---

## Detailed Findings

---

### R-01 · `git_stats.py` · **BLOCKING — subprocess handle leak**

**Location:** `src/code_compass/analysis/git_stats.py`, lines 23–35  

**Problem:**  
`Repo(str(root), search_parent_directories=False)` is assigned to a plain local variable
and never explicitly closed. GitPython lazily spawns a `git cat-file --batch` persistent
subprocess the first time object data is requested; this handle remains open until the
`Repo` object is garbage-collected. CPython's refcount GC frees it promptly at function
return, but:

1. The spec (ST-4, check 5) explicitly requires no leaking subprocess handles.
2. Under PyPy / any tracing GC, `__del__` is non-deterministic — the handle can outlive
   many invocations, exhausting OS file-descriptor limits on large batch runs.
3. GitPython exposes a `close()` method and a `__enter__`/`__exit__` context-manager pair
   precisely to address this.

**Fix:** Wrap the `Repo` construction and all uses inside `with Repo(...) as repo:`.  
Applied to `src/code_compass/analysis/git_stats.py`.

---

### R-02 · `js_analyzer.py` · **BLOCKING — duplicate CallEdge entries**

**Location:** `src/code_compass/analysis/js_analyzer.py`, lines 103–128  

**Problem:**  
When a function/method node is encountered in the outer DFS loop (line 103), two things
happen:

1. `_collect_calls(node, ...)` walks the **entire subtree** of the function and records
   every `call_expression` under that function as a `CallEdge` (lines 116, 149–163).
2. `for child in node.children: stack.append((child, qualified))` pushes all of the
   function's direct children onto the outer DFS stack (lines 117–118).

As the outer DFS continues it will reach those same `call_expression` nodes again via the
fall-through branch at lines 121–125, adding a second `CallEdge` for each call. On a file
with N calls inside functions, this produces 2N call edges — half of them duplicates.

**Concrete example:**

```js
function foo() { bar(); baz(); }
```

`_collect_calls` records `foo→bar` and `foo→baz`.  
The outer DFS then descends into `foo`'s children, finds `bar()` and `baz()` again, and
appends `foo→bar` and `foo→baz` a second time because `prefix == "foo"` at that point.

This corrupts the call graph, inflates edge counts, and will cause dead-code analysis to
incorrectly mark symbols as referenced more times than they actually are.

**Fix:** After processing a function/class node, do **not** push its children back onto
the outer DFS stack. `_collect_calls` already performs a full subtree walk for calls; the
outer DFS only needs to descend into nested *definitions* (classes/functions). The
existing `continue` after the class branch already demonstrates the right pattern — the
function branch was missing the corresponding scope isolation.

Applied to `src/code_compass/analysis/js_analyzer.py`.

---

### R-03 · `discovery.py` · PASS — `os.scandir` is truly iterative

`os.scandir(current_dir)` returns an `os.ScandirIterator` object.  
It is immediately wrapped in a `with entries:` context manager and consumed lazily inside
`for entry in entries`. The only list grown is the explicit DFS `stack` (one `Path` per
subdirectory) and `manifest.files` (one `FileRecord` per file) — both are unavoidable.
No intermediate materialisation of the directory listing was observed.

---

### R-04 · `discovery.py` · PASS — symlink check precedes `is_dir()`

Line 108 (`if entry.is_symlink(): continue`) executes unconditionally before line 111
(`if entry.is_dir(follow_symlinks=False)`). The belt-and-suspenders `follow_symlinks=False`
argument is also present on `is_dir()` and `is_file()`, preventing accidental symlink
traversal even if the order were ever swapped.

---

### R-05 · `discovery.py` · PASS — `_is_binary` has no file-handle leak

`_is_binary` uses `with path.open("rb") as fh:` (lines 66–68). The `with` block
guarantees the handle is closed before `return` regardless of whether `fh.read()` raises.

---

### R-06 · `orchestrator.py` · PASS — no retained file contents, no redundant list

`analyze_python` / `analyze_js` receive only a `Path` and return extracted primitive
dataclass lists. No file text, no AST, and no raw bytes are assigned to any variable in
`orchestrator.py`. The `result.symbols` / `result.call_edges` / `result.parse_errors`
lists are the single authoritative accumulator — there is no secondary copy.

The `parse_errors` append (`f"{record.path}: {exc}"`) formats `exc` to a string
immediately, so the exception object (and any traceback reference to the source frame) is
not stored.

---

### R-07 · `python_analyzer.py` · PASS — AST not stored on AnalysisResult

`tree = ast.parse(source, ...)` is a function-local variable. The function returns
`(symbols, call_edges)` — both are `list[SymbolInfo]` / `list[CallEdge]` containing only
primitive fields (`str`, `int`). `tree` is not included in the return value and is not
attached to any long-lived object.

*Non-blocking note:* `source` (up to 512 KB of file text) and `tree` remain alive for the
duration of `analyze_python`'s stack frame. This is unavoidable with the stdlib `ast` API
and is within the file-size budget established by ST-2 (`MAX_FILE_BYTES = 512 KB`).

---

### R-08 · `js_analyzer.py` · PASS — Parser/Language are module-level singletons

`_JS_LANGUAGE`, `_TS_LANGUAGE`, `_JS_PARSER`, `_TS_PARSER` are defined at module scope
(lines 25–29) and initialized exactly once at import time. `analyze_js` selects the
appropriate singleton via a ternary (`_TS_PARSER if language == "typescript" else
_JS_PARSER`) and calls `parser.parse()` — no `Parser(...)` or `Language(...)` constructor
call appears inside `analyze_js`.

---

### R-09 · `js_analyzer.py` · NON-BLOCKING — Parser singletons not thread-safe

**Risk (not a bug today):**  
tree-sitter's `Parser` object maintains internal C-level mutable state. The module-level
singletons `_JS_PARSER` and `_TS_PARSER` are not protected by a lock. If the orchestrator
is ever parallelised (e.g., `ThreadPoolExecutor`), two concurrent calls to
`_JS_PARSER.parse()` will race on the same object and produce corrupt parse trees or
segfaults.

The current orchestrator is single-threaded, so this is not an active defect. A future
parallel orchestrator must either:
- Use `threading.local()` to give each thread its own `Parser` instance, or
- Protect `parser.parse()` with a `threading.Lock`.

No fix applied in this review cycle. Flagged for ST-8 / future parallel work.

---

### R-10 · `python_analyzer.py` · NON-BLOCKING — `source` and `tree` live during traversal

`source` (file text string) and `tree` (full AST) both remain live for the entire
execution of `analyze_python`. For a 512 KB Python file, the AST can be 20–50 MB in
memory. Since the orchestrator currently processes files sequentially, peak memory is
bounded to one file at a time — acceptable. If the orchestrator is ever parallelised this
becomes a more significant concern (N workers × 50 MB each).

No fix required; noted for parallel-orchestrator design.

---

## Amendments Applied

### Fix R-01 — `git_stats.py`

Used `with Repo(...) as repo:` so that `repo.close()` is called deterministically when
the `with` block exits, regardless of exceptions. The `try/except` for git errors wraps
the entire `with` body.

### Fix R-02 — `js_analyzer.py`

Added `continue` after the `_CALL_TYPES` branch in the outer DFS loop so that a
`call_expression` node's children are **never pushed** back onto the outer stack.

**Root cause recap:**
When a function node is processed, `_collect_calls(node, ...)` performs a full DFS of the
entire function subtree and records every `CallEdge`. The outer DFS then also pushes the
function's children back onto its stack (for nested symbol discovery). When the outer DFS
later reached those same `call_expression` nodes, it entered the `_CALL_TYPES` branch and
recorded the same edge a second time.

**Why `continue` is safe:**
A `call_expression` node contains the callee expression and argument list — never a
`function_declaration`, `method_definition`, or `class_declaration`. There are no symbol
definitions to discover inside a call expression, so cutting the outer DFS descent at this
point loses nothing.

**Result:**
- Module-level calls (where `prefix` is empty) are still recorded correctly.
- Calls inside functions are recorded exactly once by `_collect_calls`.
- Nested function/class definitions inside functions are still discovered because the
  function-node branch still pushes all of the function's children onto the outer DFS
  stack — the `continue` only fires when the outer DFS *reaches* a call-expression node,
  not when it processes the containing function.
