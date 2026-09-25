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
    # Node's WebSocket client (the TypeScript SDK) broke on compressed frames.
    assert captured["ws_per_message_deflate"] is False
    assert captured["port"] == 9999


# ── Phase 40 Slice 3: persistence and proxy configuration ──────────────────


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> dict:
    import uvicorn

    from arena.server.__main__ import main

    captured: dict = {}

    def fake_run(app, **kwargs):  # type: ignore[no-untyped-def]
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    main(["--log-level", "WARNING", *argv])
    return captured


def test_the_default_store_is_bounded_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    from arena.server.transcript_store import DEFAULT_MEMORY_MAX_BYTES, MemoryTranscriptStore

    for name in ("ARENA_TRANSCRIPT_STORE", "ARENA_CLIENT_IP_HEADER"):
        monkeypatch.delenv(name, raising=False)
    app = _run_main(monkeypatch, [])["app"]
    store = app.state.transcript_store
    assert isinstance(store, MemoryTranscriptStore)
    assert store.policy.max_bytes == DEFAULT_MEMORY_MAX_BYTES
    assert app.state.client_ip_header is None


def test_flags_configure_a_durable_store(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from arena.server.transcript_store import DEFAULT_MAX_BYTES, SqliteTranscriptStore

    path = tmp_path / "arena.sqlite3"
    app = _run_main(
        monkeypatch,
        [
            "--transcript-store",
            f"sqlite:{path}",
            "--transcript-ttl-s",
            "3600",
            "--transcript-max-entries",
            "50",
            "--client-ip-header",
            "Fly-Client-IP",
        ],
    )["app"]
    store = app.state.transcript_store
    try:
        assert isinstance(store, SqliteTranscriptStore)
        assert (store.policy.ttl_s, store.policy.max_entries) == (3600.0, 50)
        assert store.policy.max_bytes == DEFAULT_MAX_BYTES
        assert app.state.client_ip_header == "Fly-Client-IP"
    finally:
        store.close()


def test_environment_variables_configure_the_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from arena.server.transcript_store import FileTranscriptStore

    monkeypatch.setenv("ARENA_TRANSCRIPT_STORE", f"file:{tmp_path / 't'}")
    monkeypatch.setenv("ARENA_TRANSCRIPT_TTL_S", "120")
    monkeypatch.setenv("ARENA_TRANSCRIPT_MAX_BYTES", "4096")
    store = _run_main(monkeypatch, [])["app"].state.transcript_store
    assert isinstance(store, FileTranscriptStore)
    assert (store.policy.ttl_s, store.policy.max_bytes) == (120.0, 4096)


@pytest.mark.parametrize(
    ("argv", "env"),
    [
        (["--transcript-store", "postgres:x"], {}),
        (["--transcript-ttl-s", "0"], {}),
        ([], {"ARENA_TRANSCRIPT_MAX_ENTRIES": "zero"}),
    ],
)
def test_bad_settings_exit_with_a_usage_error(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], env: dict
) -> None:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(SystemExit) as info:
        _run_main(monkeypatch, argv)
    assert info.value.code == 2


def test_a_trusted_client_ip_header_buckets_rate_limits() -> None:
    from fastapi.testclient import TestClient

    from arena.server.app import create_app
    from arena.server.rate_limits import RateLimiter

    app = create_app(
        rate_limiter=RateLimiter(max_transcript_reads_per_ip_per_min=1),
        client_ip_header="Fly-Client-IP",
    )
    url = "/matches/unknown/public-transcript"
    with TestClient(app) as client:
        assert client.get(url, headers={"Fly-Client-IP": "1.1.1.1"}).status_code == 404
        # Same peer, different client behind the proxy: its own bucket.
        assert client.get(url, headers={"Fly-Client-IP": "2.2.2.2"}).status_code == 404
        assert client.get(url, headers={"Fly-Client-IP": "1.1.1.1"}).status_code == 429


def test_without_the_setting_the_header_is_ignored() -> None:
    from fastapi.testclient import TestClient

    from arena.server.app import create_app
    from arena.server.rate_limits import RateLimiter

    app = create_app(rate_limiter=RateLimiter(max_transcript_reads_per_ip_per_min=1))
    url = "/matches/unknown/public-transcript"
    with TestClient(app) as client:
        assert client.get(url, headers={"Fly-Client-IP": "1.1.1.1"}).status_code == 404
        assert client.get(url, headers={"Fly-Client-IP": "2.2.2.2"}).status_code == 429


def test_an_unopenable_store_is_a_usage_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    with pytest.raises(SystemExit) as info:
        _run_main(monkeypatch, ["--transcript-store", f"sqlite:{blocker / 'db.sqlite3'}"])
    assert info.value.code == 2
