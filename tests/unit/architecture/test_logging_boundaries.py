"""Ensure lower layers never call logging.getLogger at module scope.

Only ``arena.server`` is allowed to configure logging / obtain module-scope
loggers.  Lower layers must remain silent at import time.
"""

from __future__ import annotations

import ast
import pathlib

LOWER_LAYER_ROOTS = [
    "src/arena/core",
    "src/arena/games",
    "src/arena/match",
    "src/arena/adapters",
    "src/arena/runtime",
    "src/arena/ui",
    "src/arena/cli",
    "src/arena/sdk",
]


def _has_module_scope_get_logger(src: str) -> bool:
    """Return True if the module calls logging.getLogger at module scope.

    Only checks top-level nodes (not inside functions or classes) to avoid
    flagging legitimate lazy-initialisation patterns inside callables.
    """
    tree = ast.parse(src)
    for node in ast.iter_child_nodes(tree):  # only top-level nodes
        if isinstance(node, ast.Assign):
            for v in ast.walk(node.value):
                if (
                    isinstance(v, ast.Call)
                    and isinstance(v.func, ast.Attribute)
                    and v.func.attr == "getLogger"
                ):
                    return True
        elif isinstance(node, ast.Expr):
            if (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and node.value.func.attr == "getLogger"
            ):
                return True
    return False


def test_no_module_scope_loggers_in_lower_layers() -> None:
    """No lower-layer module may call logging.getLogger at module scope."""
    root = pathlib.Path(__file__).parents[3]  # repo root
    violations: list[str] = []
    for layer in LOWER_LAYER_ROOTS:
        layer_path = root / layer
        if not layer_path.exists():
            continue
        for py_file in layer_path.rglob("*.py"):
            src = py_file.read_text(encoding="utf-8")
            if _has_module_scope_get_logger(src):
                violations.append(str(py_file.relative_to(root)))
    assert violations == [], (
        "Module-scope logging.getLogger found in lower layers:\n"
        + "\n".join(f"  {v}" for v in violations)
    )
