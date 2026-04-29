"""Import-boundary tests for arena.server."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src" / "arena"


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


def test_lower_layers_do_not_import_server() -> None:
    """No file under core, games, match, adapters, runtime, ui, cli, or agents
    may import arena.server.
    """
    lower_packages = ("core", "games", "match", "adapters", "runtime", "ui", "cli", "agents")
    violations: list[str] = []

    for package in lower_packages:
        for path in _python_files(package):
            for imported_module in _imported_modules(path):
                if imported_module.startswith("arena.server"):
                    relative = path.relative_to(PROJECT_ROOT)
                    violations.append(f"{relative}: {imported_module}")

    assert violations == []


def test_server_does_not_import_sdk() -> None:
    """arena.server must not import arena.sdk or arena.cli."""
    violations: list[str] = []

    for path in _python_files("server"):
        for imported_module in _imported_modules(path):
            if imported_module.startswith(("arena.sdk", "arena.cli")):
                relative = path.relative_to(PROJECT_ROOT)
                violations.append(f"{relative}: {imported_module}")

    assert violations == []
