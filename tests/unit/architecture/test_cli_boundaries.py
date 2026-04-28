"""Import-boundary tests for the arena.cli package."""

from __future__ import annotations

import ast
from pathlib import Path

import arena.cli

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


def test_arena_cli_is_importable() -> None:
    assert hasattr(arena.cli, "__all__")


def test_cli_allowed_imports() -> None:
    """arena.cli may import arena.ui and arena.runtime (and stdlib); verify by import."""
    import arena.cli.app  # noqa: F401  — import exercise only
    import arena.cli.rendering  # noqa: F401


def test_core_does_not_import_cli() -> None:
    _assert_no_forbidden_imports("core", ("arena.cli",))


def test_games_do_not_import_cli() -> None:
    _assert_no_forbidden_imports("games", ("arena.cli",))


def test_match_does_not_import_cli() -> None:
    _assert_no_forbidden_imports("match", ("arena.cli",))


def test_adapters_do_not_import_cli() -> None:
    _assert_no_forbidden_imports("adapters", ("arena.cli",))


def test_runtime_does_not_import_cli() -> None:
    _assert_no_forbidden_imports("runtime", ("arena.cli",))


def test_ui_does_not_import_cli() -> None:
    _assert_no_forbidden_imports("ui", ("arena.cli",))
