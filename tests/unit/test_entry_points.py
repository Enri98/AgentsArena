"""The console scripts (``arena._entry``): a missing extra is named, not a traceback."""

from __future__ import annotations

import sys
import types

import pytest

from arena import _entry


def _broken_module(monkeypatch: pytest.MonkeyPatch, missing: str) -> str:
    name = "_arena_test_command"

    def fail(module: str) -> types.ModuleType:
        raise ModuleNotFoundError(f"No module named '{missing}'", name=missing)

    monkeypatch.setattr(_entry.importlib, "import_module", fail)
    return name


def test_a_missing_extra_is_named(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = _broken_module(monkeypatch, "fastapi")
    with pytest.raises(SystemExit) as exit_info:
        _entry._run(module, "arena-server", "server")
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "'fastapi' package is not installed" in err
    assert "pip install 'agents-arena[server]'" in err


def test_an_unrelated_import_error_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _broken_module(monkeypatch, "numpy")
    with pytest.raises(ModuleNotFoundError):
        _entry._run(module, "arena-server", "server")


def test_help_names_the_console_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["C:\\venv\\Scripts\\arena-play.exe"])
    assert _entry.program_name("python -m arena.cli.play") == "arena-play"
    monkeypatch.setattr(sys, "argv", ["/venv/bin/arena-play"])
    assert _entry.program_name("python -m arena.cli.play") == "arena-play"
    monkeypatch.setattr(sys, "argv", ["/src/arena/cli/play/__main__.py"])
    assert _entry.program_name("python -m arena.cli.play") == "python -m arena.cli.play"


def test_the_commands_run_their_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []

    def fake_import(module: str) -> types.SimpleNamespace:
        return types.SimpleNamespace(main=lambda: ran.append(module))

    monkeypatch.setattr(_entry.importlib, "import_module", fake_import)
    monkeypatch.setattr(sys, "argv", ["x"])
    for command in (_entry.server, _entry.play, _entry.replay, _entry.mcp, _entry.scaffold):
        command()
    assert ran == [
        "arena.server.__main__",
        "arena.cli.play.__main__",
        "arena.cli.__main__",
        "arena.mcp.__main__",
        "arena.games.scaffold._cli",
    ]


def test_remote_play_without_the_client_extra_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import importlib.util

    from arena.cli.play import __main__ as play_main

    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name, *a: None if name == "websockets" else real_find_spec(name, *a),
    )
    code = play_main.main(
        [
            "--game", "tictactoe",
            "--seat-0", "scripted:1",
            "--seat-1", "scripted:2",
            "--server-url", "http://127.0.0.1:1",
        ]
    )
    assert code == 2
    assert "pip install 'agents-arena[client]'" in capsys.readouterr().err
