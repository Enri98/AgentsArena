"""Game-scaffold CLI: generate boilerplate for a new arena game.

This sub-package is the ONE place inside ``arena.games`` that performs disk
I/O. It is a code generator only — it never imports the games, runtime, CLI,
agents, MCP, or server layers. Its templates are stdlib string templates.

Invoke as ``python -m arena.games.scaffold --name <name> [--dry-run] [--force]``.
"""

from __future__ import annotations

from arena.games.scaffold._cli import main

__all__: tuple[str, ...] = ("main",)
