"""Console-script entry points (``arena-server``, ``arena-mcp``, ...).

Each loads its command's module lazily, so a command whose optional
dependencies are missing says which extra to install instead of failing with an
import traceback.
"""

from __future__ import annotations

import importlib
import sys
from typing import Any, NoReturn

#: The third-party modules each extra provides.
_EXTRA_MODULES = {
    "server": ("fastapi", "uvicorn", "structlog", "starlette", "websockets"),
    "mcp": ("mcp", "websockets"),
    "client": ("websockets",),
}


def _run(module: str, command: str, extra: str | None) -> Any:
    try:
        target = importlib.import_module(module)
    except ModuleNotFoundError as exc:
        missing = (exc.name or "").split(".")[0]
        if extra is None or missing not in _EXTRA_MODULES.get(extra, ()):
            raise
        _missing(command, missing, extra)
    # argparse names the program after sys.argv[0]: the console script's name.
    sys.argv[0] = command
    return target.main()


def _missing(command: str, module: str, extra: str) -> NoReturn:
    sys.stderr.write(
        f"{command}: the '{module}' package is not installed.\n"
        f"Install the '{extra}' extra: pip install 'agents-arena[{extra}]'\n"
    )
    raise SystemExit(2)


def server() -> Any:
    return _run("arena.server.__main__", "arena-server", "server")


def mcp() -> Any:
    return _run("arena.mcp.__main__", "arena-mcp", "mcp")


def play() -> Any:
    return _run("arena.cli.play.__main__", "arena-play", "client")


def replay() -> Any:
    return _run("arena.cli.__main__", "arena-replay", None)


def scaffold() -> Any:
    return _run("arena.games.scaffold._cli", "arena-scaffold", None)


def program_name(module_form: str) -> str:
    """The program name for ``--help``: the console script when run as one,
    else ``module_form`` (``python -m arena.cli.play``)."""

    name = sys.argv[0].replace("\\", "/").rsplit("/", 1)[-1] if sys.argv else ""
    if name.endswith(".exe"):
        name = name[: -len(".exe")]
    return name if name.startswith("arena-") else module_form
