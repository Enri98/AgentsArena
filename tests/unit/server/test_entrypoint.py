"""The production entry point must run the WebSocket implementation the handlers
need (found by a real-server check during Phase 38: every match aborted
peer_disconnected under the default implementation, while every test passed on
sansio)."""

from __future__ import annotations

import sys

import pytest


def test_python_m_arena_server_runs_sansio(monkeypatch: pytest.MonkeyPatch) -> None:
    import uvicorn

    from arena.server.__main__ import main
    from arena.server.config import UVICORN_WS_IMPL

    captured: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(sys, "argv", ["arena.server", "--port", "9999", "--log-level", "WARNING"])
    main()

    assert UVICORN_WS_IMPL == "websockets-sansio"
    assert captured["ws"] == UVICORN_WS_IMPL
    # A dead reader (a spectator that stopped reading) is found and dropped.
    assert captured["ws_ping_interval"] > 0 and captured["ws_ping_timeout"] > 0
    assert captured["ws_max_size"] <= 1 << 20
    assert captured["port"] == 9999
