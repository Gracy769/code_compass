"""code_compass.analysis.python_analyzer — stdlib-ast based Python analysis."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from code_compass.analysis.models import CallEdge, SymbolInfo

# Branch node types that each add 1 to McCabe complexity.
_BRANCH_TYPES = (
    ast.If,
    ast.For,
    ast.While,
    ast.ExceptHandler,
    ast.With,
    ast.BoolOp,
    ast.Assert,
)


def _mccabe(func_node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    """Return McCabe cyclomatic complexity for *func_node*.

    Complexity = 1 + number of branch nodes in the function body.
    """
    count = 1
    for node in ast.walk(func_node):
        if node is func_node:
            continue
        if isinstance(node, _BRANCH_TYPES):
            count += 1
    return count


def analyze_python(path: Path) -> tuple[list[SymbolInfo], list[CallEdge]]:
    """Parse *path* with stdlib :mod:`ast` and extract symbols and call edges.

    Returns a ``(symbols, call_edges)`` tuple.  Raises any parse exception to
    the caller — the orchestrator is responsible for catching and logging it.
    """
    source = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=str(path))

    symbols: list[SymbolInfo] = []
    call_edges: list[CallEdge] = []
    file_str = str(path)

    # Stack entries: (ast_node, qualified_prefix)
    stack: list[tuple[ast.AST, str]] = [(tree, "")]

    while stack:
        node, prefix = stack.pop()

        children_to_visit: list[ast.AST] = []

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            kind = "async_function" if isinstance(node, ast.AsyncFunctionDef) else "function"
            complexity = _mccabe(node)
            qualified = f"{prefix}.{node.name}".lstrip(".")
            symbols.append(
                SymbolInfo(
                    name=node.name,
                    kind=kind,
                    file=file_str,
                    line=node.lineno,
                    complexity=complexity,
                )
            )
            # Collect calls inside this function
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    callee = _call_name(child)
                    if callee:
                        call_edges.append(CallEdge(caller=qualified, callee=callee))

            # Recurse into nested definitions
            children_to_visit = list(ast.iter_child_nodes(node))
            for child in children_to_visit:
                stack.append((child, qualified))
            continue

        elif isinstance(node, ast.ClassDef):
            qualified = f"{prefix}.{node.name}".lstrip(".")
            symbols.append(
                SymbolInfo(
                    name=node.name,
                    kind="class",
                    file=file_str,
                    line=node.lineno,
                    complexity=1,
                )
            )
            for child in ast.iter_child_nodes(node):
                stack.append((child, qualified))
            continue

        # For module-level and other nodes, recurse into direct children only
        for child in ast.iter_child_nodes(node):
            stack.append((child, prefix))

    return symbols, call_edges


def _call_name(call: ast.Call) -> str | None:
    """Best-effort extraction of the callee name from an :class:`ast.Call` node."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None
