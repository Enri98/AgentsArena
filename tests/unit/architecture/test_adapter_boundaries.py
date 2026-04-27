"""Import-boundary tests for future adapter work."""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src" / "arena"


def _python_files(package: str) -> tuple[Path, ...]:
    return tuple((SOURCE_ROOT / package).rglob("*.py"))


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)

    return imports


def _assert_no_forbidden_imports(package: str, forbidden_prefixes: tuple[str, ...]) -> None:
    violations: list[str] = []

    for path in _python_files(package):
        for imported_module in _imported_modules(path):
            if imported_module.startswith(forbidden_prefixes):
                relative_path = path.relative_to(PROJECT_ROOT)
                violations.append(f"{relative_path}: {imported_module}")

    assert violations == []


def test_core_and_games_do_not_depend_on_match_or_future_adapters() -> None:
    forbidden_prefixes = ("arena.match", "arena.adapters")

    _assert_no_forbidden_imports("core", forbidden_prefixes)
    _assert_no_forbidden_imports("games", forbidden_prefixes)


def test_match_does_not_depend_on_future_adapters() -> None:
    _assert_no_forbidden_imports("match", ("arena.adapters",))
