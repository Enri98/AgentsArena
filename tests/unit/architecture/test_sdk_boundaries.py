"""Import-boundary tests for arena.sdk."""
from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PROJECT_ROOT / "src" / "arena"

FORBIDDEN_SDK_IMPORTS = (
    "arena.match",
    "arena.adapters.in_process",
    "arena.runtime",
    "arena.ui",
    "arena.cli",
    "arena.server",
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


def test_sdk_does_not_import_forbidden_layers() -> None:
    """arena.sdk must not import arena.match, arena.adapters.in_process,
    arena.runtime, arena.ui, arena.cli, or arena.server."""
    violations: list[str] = []
    for path in _python_files("sdk"):
        for mod in _imported_modules(path):
            if mod.startswith(FORBIDDEN_SDK_IMPORTS):
                relative = path.relative_to(PROJECT_ROOT)
                violations.append(f"{relative}: {mod}")
    assert violations == [], "\n".join(violations)


def test_lower_layers_do_not_import_sdk() -> None:
    """No layer below arena.sdk may import it."""
    lower_packages = (
        "core", "games", "match", "adapters", "runtime", "ui", "agents",
    )
    violations: list[str] = []
    for package in lower_packages:
        for path in _python_files(package):
            for mod in _imported_modules(path):
                if mod.startswith("arena.sdk"):
                    relative = path.relative_to(PROJECT_ROOT)
                    violations.append(f"{relative}: {mod}")
    assert violations == [], "\n".join(violations)
