"""Import-boundary tests for the adapter, runtime, and UI packages."""

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
    # arena.adapters prefix already covers arena.adapters.websocket
    forbidden_prefixes = ("arena.match", "arena.adapters", "arena.runtime")

    _assert_no_forbidden_imports("core", forbidden_prefixes)
    _assert_no_forbidden_imports("games", forbidden_prefixes)


def test_match_does_not_import_adapters_or_runtime() -> None:
    # arena.adapters prefix already covers arena.adapters.websocket
    _assert_no_forbidden_imports("match", ("arena.adapters", "arena.runtime"))


def test_in_process_adapter_does_not_import_runtime() -> None:
    # arena.adapters.in_process must not import any arena.runtime module
    violations: list[str] = []
    in_process = SOURCE_ROOT / "adapters" / "in_process.py"
    if not in_process.exists():
        return
    for imported_module in _imported_modules(in_process):
        if imported_module.startswith("arena.runtime"):
            violations.append(f"adapters/in_process.py: {imported_module}")
    assert violations == []


def test_websocket_adapter_only_imports_core_in_process_and_runtime_payloads() -> None:
    """arena.adapters.websocket may only import arena.core.*, arena.adapters.in_process,
    and arena.runtime.payloads. Networking libs and all other arena layers are forbidden.
    """
    ws_root = SOURCE_ROOT / "adapters" / "websocket"
    if not ws_root.exists():
        return

    # Modules rooted here that are allowed
    allowed_arena_prefixes = (
        "arena.core",
        "arena.adapters.websocket",  # intra-package imports
    )
    allowed_arena_exact = {
        "arena.adapters.in_process",
        "arena.runtime.payloads",
    }
    forbidden_networking = {
        "websockets",
        "aiohttp",
        "httpx",
        "fastapi",
        "socket",
        "asyncio",
    }
    forbidden_arena_prefixes = (
        "arena.match",
        "arena.runtime.models",
        "arena.runtime.session",
        "arena.runtime.formatting",
        "arena.runtime.exceptions",
        "arena.ui",
        "arena.cli",
        "arena.server",
        "arena.sdk",
        "arena.agents",
    )

    violations: list[str] = []

    for path in ws_root.rglob("*.py"):
        relative_path = path.relative_to(PROJECT_ROOT)
        for imported_module in _imported_modules(path):
            # Networking libraries are always forbidden
            base = imported_module.split(".")[0]
            if base in forbidden_networking:
                violations.append(f"{relative_path}: {imported_module} (networking lib)")
                continue

            if not imported_module.startswith("arena."):
                continue

            # Explicit denials first
            if imported_module.startswith(forbidden_arena_prefixes):
                violations.append(f"{relative_path}: {imported_module}")
                continue

            # arena.runtime.* is only allowed as arena.runtime.payloads exactly
            if imported_module.startswith("arena.runtime") and (
                imported_module not in allowed_arena_exact
            ):
                violations.append(f"{relative_path}: {imported_module}")
                continue

            # arena.adapters.* is only allowed as in_process or intra-websocket
            if imported_module.startswith("arena.adapters") and (
                imported_module not in allowed_arena_exact
                and not imported_module.startswith("arena.adapters.websocket")
            ):
                violations.append(f"{relative_path}: {imported_module}")
                continue

            # arena.core.* allowed; arena.adapters.in_process allowed; intra-package allowed
            if imported_module.startswith(allowed_arena_prefixes):
                continue
            if imported_module in allowed_arena_exact:
                continue

            # Any other arena.* import is a violation
            violations.append(f"{relative_path}: {imported_module}")

    assert violations == []


def test_runtime_package_does_not_import_websocket_adapter() -> None:
    """arena.runtime must not import arena.adapters.websocket."""
    runtime_root = SOURCE_ROOT / "runtime"
    if not runtime_root.exists():
        return

    violations: list[str] = []
    for path in _python_files("runtime"):
        relative_path = path.relative_to(PROJECT_ROOT)
        for imported_module in _imported_modules(path):
            if imported_module.startswith("arena.adapters.websocket"):
                violations.append(f"{relative_path}: {imported_module}")

    assert violations == []


def test_ui_package_does_not_import_websocket_adapter() -> None:
    """arena.ui must not import arena.adapters.websocket."""
    ui_root = SOURCE_ROOT / "ui"
    if not ui_root.exists():
        return

    violations: list[str] = []
    for path in _python_files("ui"):
        relative_path = path.relative_to(PROJECT_ROOT)
        for imported_module in _imported_modules(path):
            if imported_module.startswith("arena.adapters.websocket"):
                violations.append(f"{relative_path}: {imported_module}")

    assert violations == []


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
                # arena.adapters.websocket is explicitly excluded from runtime's allowed set
                if imported_module.startswith("arena.adapters.websocket"):
                    violations.append(f"{relative_path}: {imported_module}")
                continue

            if imported_module == "arena":
                continue

            if imported_module.startswith("arena."):
                violations.append(f"{relative_path}: {imported_module}")

    assert violations == []


def test_ui_package_depends_only_on_runtime_within_arena_when_it_exists() -> None:
    ui_root = SOURCE_ROOT / "ui"

    if not ui_root.exists():
        return

    violations: list[str] = []

    for path in _python_files("ui"):
        relative_path = path.relative_to(PROJECT_ROOT)

        for imported_module in _imported_modules(path):
            if imported_module.startswith(("arena.runtime", "arena.ui")):
                continue

            if imported_module == "arena":
                continue

            if imported_module.startswith("arena."):
                violations.append(f"{relative_path}: {imported_module}")

    assert violations == []
