"""Concrete game packages built on the shared simulation core."""

from __future__ import annotations

from collections.abc import Sequence

from arena.core.registry import GameRegistry


def register_builtin_games(registry: GameRegistry) -> None:
    """Register the built-in game set in a supplied registry."""

    from arena.games.connect4.definition import register_connect4
    from arena.games.tictactoe.definition import register_tictactoe

    register_connect4(registry)
    register_tictactoe(registry)


def build_default_registry() -> GameRegistry:
    """Build a new registry populated with the built-in games."""

    registry = GameRegistry()
    register_builtin_games(registry)
    return registry


__all__: Sequence[str] = [
    "build_default_registry",
    "connect4",
    "tictactoe",
    "register_builtin_games",
]
