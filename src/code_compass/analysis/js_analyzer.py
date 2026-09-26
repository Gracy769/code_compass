"""code_compass.analysis.js_analyzer — tree-sitter based JS/TS analysis.

Parser and Language objects are module-level singletons — created once and
reused for every file parsed, as required by the specification.

Uses the first-party tree-sitter-javascript / tree-sitter-typescript packages
(tree-sitter >= 0.24 API) instead of the unmaintained tree-sitter-languages
bundle, which has no wheel for Python 3.14+.
"""

from __future__ import annotations

from pathlib import Path

import tree_sitter_javascript as tjs
import tree_sitter_typescript as tts
from tree_sitter import Language, Parser

from code_compass.analysis.models import CallEdge, SymbolInfo

# ---------------------------------------------------------------------------
# Module-level singletons — instantiate ONCE, never per file.
# ---------------------------------------------------------------------------

_JS_LANGUAGE = Language(tjs.language())
_TS_LANGUAGE = Language(tts.language_typescript())

_JS_PARSER = Parser(_JS_LANGUAGE)
_TS_PARSER = Parser(_TS_LANGUAGE)

# Node type sets
_FUNCTION_TYPES = frozenset(
    {
        "function_declaration",
        "function_expression",
        "arrow_function",
        "method_definition",
        "generator_function_declaration",
        "generator_function",
    }
)

_CLASS_TYPES = frozenset({"class_declaration", "class"})

_CALL_TYPES = frozenset({"call_expression"})

_IDENTIFIER_FIELD = "name"


def _node_text(node, source_bytes: bytes) -> str:
    """Return the UTF-8 text of *node* from *source_bytes*."""
    return source_bytes[node.start_byte: node.end_byte].decode("utf-8", errors="replace")


def _get_name(node, source_bytes: bytes) -> str | None:
    """Extract the identifier name from a function/class node, or return None."""
    # method_definition and function_declaration have a direct 'name' child field
    name_node = node.child_by_field_name("name")
    if name_node is not None:
        return _node_text(name_node, source_bytes)
    # For anonymous functions stored in a variable: `const foo = () => {}`
    # The name comes from the parent variable_declarator.
    return None


def analyze_js(path: Path, language: str) -> tuple[list[SymbolInfo], list[CallEdge]]:
    """Parse *path* with tree-sitter and extract symbols and call edges.

    *language* must be ``'javascript'`` or ``'typescript'``.

    Returns ``(symbols, call_edges)``.  Raises any exception to the caller.
    """
    parser = _TS_PARSER if language == "typescript" else _JS_PARSER
    source_bytes = path.read_bytes()
    tree = parser.parse(source_bytes)

    symbols: list[SymbolInfo] = []
    call_edges: list[CallEdge] = []
    file_str = str(path)

    # DFS stack: (node, qualified_prefix)
    stack = [(tree.root_node, "")]

    while stack:
        node, prefix = stack.pop()

        if node.type in _CLASS_TYPES:
            name = _get_name(node, source_bytes) or "<anonymous>"
            qualified = f"{prefix}.{name}".lstrip(".")
            symbols.append(
                SymbolInfo(
                    name=name,
                    kind="class",
                    file=file_str,
                    line=node.start_point[0] + 1,  # 0-indexed → 1-indexed
                    complexity=1,
                )
            )
            for child in node.children:
                stack.append((child, qualified))
            continue

        if node.type in _FUNCTION_TYPES:
            name = _get_name(node, source_bytes) or _infer_name_from_parent(node, source_bytes)
            qualified = f"{prefix}.{name}".lstrip(".")
            symbols.append(
                SymbolInfo(
                    name=name,
                    kind="function",
                    file=file_str,
                    line=node.start_point[0] + 1,
                    complexity=1,
                )
            )
            # Collect calls inside this function
            _collect_calls(node, source_bytes, qualified, call_edges)
            for child in node.children:
                stack.append((child, qualified))
            continue

        if node.type in _CALL_TYPES:
            # Module-level calls only.  Calls *inside* a function are already
            # recorded by _collect_calls above; do not descend further here to
            # avoid duplicate CallEdge entries.
            callee = _call_expression_name(node, source_bytes)
            if callee and prefix:
                call_edges.append(CallEdge(caller=prefix, callee=callee))
            continue  # call_expression children hold no symbol definitions

        for child in node.children:
            stack.append((child, prefix))

    return symbols, call_edges


def _infer_name_from_parent(node, source_bytes: bytes) -> str:
    """Try to infer a function name from its assignment context."""
    parent = node.parent
    if parent is None:
        return "<anonymous>"
    if parent.type == "variable_declarator":
        name_node = parent.child_by_field_name("name")
        if name_node is not None:
            return _node_text(name_node, source_bytes)
    if parent.type == "assignment_expression":
        left = parent.child_by_field_name("left")
        if left is not None:
            return _node_text(left, source_bytes)
    return "<anonymous>"


def _collect_calls(
    func_node,
    source_bytes: bytes,
    caller: str,
    call_edges: list[CallEdge],
) -> None:
    """Walk *func_node* recursively and append :class:`CallEdge` items."""
    stack = list(func_node.children)
    while stack:
        node = stack.pop()
        if node.type in _CALL_TYPES:
            callee = _call_expression_name(node, source_bytes)
            if callee:
                call_edges.append(CallEdge(caller=caller, callee=callee))
        stack.extend(node.children)


def _call_expression_name(node, source_bytes: bytes) -> str | None:
    """Extract the callee name from a call_expression node."""
    func_node = node.child_by_field_name("function")
    if func_node is None:
        return None
    if func_node.type == "identifier":
        return _node_text(func_node, source_bytes)
    if func_node.type == "member_expression":
        prop = func_node.child_by_field_name("property")
        if prop is not None:
            return _node_text(prop, source_bytes)
    return None
