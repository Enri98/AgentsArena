"""Bootstrap smoke tests for package installation and discovery."""

from importlib import import_module


def test_import_arena_package() -> None:
    module = import_module("arena")

    assert module.__name__ == "arena"


def test_import_arena_core_package() -> None:
    module = import_module("arena.core")

    assert module.__name__ == "arena.core"


def test_import_arena_games_package() -> None:
    module = import_module("arena.games")

    assert module.__name__ == "arena.games"


def test_import_connect4_package() -> None:
    module = import_module("arena.games.connect4")

    assert module.__name__ == "arena.games.connect4"
