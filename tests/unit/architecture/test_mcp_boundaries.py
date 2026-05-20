"""Import-boundary tests for arena.mcp."""
from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src" / "arena"

FORBIDDEN_MCP_IMPORTS = (
    "arena.server",
    "arena.runtime",
    "arena.match",
    "arena.adapters",
    "arena.ui",
    "arena.cli",
)


def _python_files(package: str) -> tuple[Path, ...]:
    package_root = SOURCE_ROOT / package
    if not package_root.exists():
        return ()
    return tuple(package_root.rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def test_mcp_does_not_import_forbidden_layers() -> None:
    """arena.mcp may NOT import from arena.server, arena.runtime, arena.match,
    arena.adapters, arena.ui, or arena.cli."""
    violations: list[str] = []
    for path in _python_files("mcp"):
        for mod in _imported_modules(path):
            if mod.startswith(FORBIDDEN_MCP_IMPORTS):
                relative = path.relative_to(PROJECT_ROOT)
                violations.append(f"{relative}: {mod}")
    assert violations == [], "\n".join(violations)


def test_lower_layers_do_not_import_mcp() -> None:
    """No layer below arena.mcp may import it."""
    lower_packages = (
        "core",
        "games",
        "match",
        "adapters",
        "runtime",
        "ui",
        "agents",
        "cli",
        "sdk",
        "server",
    )
    violations: list[str] = []
    for package in lower_packages:
        for path in _python_files(package):
            for mod in _imported_modules(path):
                if mod.startswith("arena.mcp"):
                    relative = path.relative_to(PROJECT_ROOT)
                    violations.append(f"{relative}: {mod}")
    assert violations == [], "\n".join(violations)
