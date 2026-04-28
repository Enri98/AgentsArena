"""Import-boundary tests for the deferred runtime package."""

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


def _assert_no_forbidden_imports(package: str, forbidden_prefixes: tuple[str, ...]) -> None:
    violations: list[str] = []

    for path in _python_files(package):
        for imported_module in _imported_modules(path):
            if imported_module.startswith(forbidden_prefixes):
                relative_path = path.relative_to(PROJECT_ROOT)
                violations.append(f"{relative_path}: {imported_module}")

    assert violations == []


def test_core_and_games_do_not_import_match_adapters_or_runtime() -> None:
    forbidden_prefixes = ("arena.match", "arena.adapters", "arena.runtime")

    _assert_no_forbidden_imports("core", forbidden_prefixes)
    _assert_no_forbidden_imports("games", forbidden_prefixes)


def test_match_does_not_import_adapters_or_runtime() -> None:
    _assert_no_forbidden_imports("match", ("arena.adapters", "arena.runtime"))


def test_adapters_do_not_import_runtime() -> None:
    _assert_no_forbidden_imports("adapters", ("arena.runtime",))


def test_runtime_package_may_depend_on_core_match_and_adapters_when_it_exists() -> None:
    runtime_root = SOURCE_ROOT / "runtime"

    if not runtime_root.exists():
        return

    violations: list[str] = []

    for path in _python_files("runtime"):
        relative_path = path.relative_to(PROJECT_ROOT)

        for imported_module in _imported_modules(path):
            if imported_module.startswith(
                ("arena.core", "arena.match", "arena.adapters", "arena.runtime")
            ):
                continue

            if imported_module == "arena":
                continue

            if imported_module.startswith("arena."):
                violations.append(f"{relative_path}: {imported_module}")

    assert violations == []
