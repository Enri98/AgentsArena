"""Server hardening from the pre-Phase 40 adversarial review (single-socket tests).

Each test is a confirmed finding; anything needing two live sockets is in
``tests/integration/test_review_hardening.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from arena.adapters.websocket import WIRE_SCHEMA_VERSION, dumps
from arena.adapters.websocket.envelope import HelloEnvelope
from arena.adapters.websocket.messages import HelloBody
from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter, RateLimitExceeded
from arena.server.registry import MatchRegistry

_MATCH = {"game_id": "tictactoe", "per_turn_deadline_ms": 2000, "disconnect_grace_ms": 500}


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _hello(seat: int, token: str | None = None) -> str:
    return dumps(
        HelloEnvelope(
            schema_version=WIRE_SCHEMA_VERSION,
            seat=seat,
            payload=HelloBody(
                client_name="t",
                client_version="0",
                supported_schema_versions=[WIRE_SCHEMA_VERSION],
                auth=None,
                requested_seat=seat,
                resume_token=token,
            ),
        )
    )


def _close_code(ws: Any) -> int | None:
    try:
        while True:
            ws.receive_text()
    except WebSocketDisconnect as exc:
        return exc.code
    return None


# ── Rate limits ────────────────────────────────────────────────────────────


def test_spectators_do_not_use_the_seats_connection_slots() -> None:
    limiter = RateLimiter(max_connections_per_match=2, max_spectators_per_match=3)
    for i in range(3):
        limiter.acquire_connection(ip=f"10.0.0.{i}", match_id="m", spectator=True)
    with pytest.raises(RateLimitExceeded) as info:
        limiter.acquire_connection(ip="10.0.0.9", match_id="m", spectator=True)
    assert info.value.scope == "spectators_per_match"
    # Both seats still get in.
    limiter.acquire_connection(ip="10.0.1.0", match_id="m")
    limiter.acquire_connection(ip="10.0.1.1", match_id="m")
    assert limiter.connection_count(match_id="m") == 2
    assert limiter.connection_count(match_id="m", spectator=True) == 3
    limiter.release_connection(ip="10.0.0.0", match_id="m", spectator=True)
    assert limiter.connection_count(match_id="m", spectator=True) == 2


def test_connection_opens_are_rate_limited_per_ip() -> None:
    clock = _Clock()
    limiter = RateLimiter(max_ws_opens_per_ip_per_min=3, time_fn=clock)
    for _ in range(3):
        limiter.acquire_connection(ip="1.2.3.4", match_id="m", spectator=True)
        limiter.release_connection(ip="1.2.3.4", match_id="m", spectator=True)
    with pytest.raises(RateLimitExceeded) as info:
        limiter.acquire_connection(ip="1.2.3.4", match_id="m", spectator=True)
    assert info.value.scope == "connection_opens_per_ip"
    limiter.acquire_connection(ip="5.6.7.8", match_id="m", spectator=True)  # others are fine
    clock.now += 61
    limiter.acquire_connection(ip="1.2.3.4", match_id="m", spectator=True)


def test_transcript_reads_are_rate_limited_per_ip() -> None:
    clock = _Clock()
    limiter = RateLimiter(max_transcript_reads_per_ip_per_min=2, time_fn=clock)
    limiter.check_transcript_read(ip="1.2.3.4")
    limiter.check_transcript_read(ip="1.2.3.4")
    with pytest.raises(RateLimitExceeded):
        limiter.check_transcript_read(ip="1.2.3.4")
    clock.now += 61
    limiter.check_transcript_read(ip="1.2.3.4")


def test_per_ip_windows_do_not_grow_without_bound() -> None:
    clock = _Clock()
    limiter = RateLimiter(time_fn=clock)
    for i in range(5000):
        limiter.check_transcript_read(ip=f"ip{i}")
    clock.now += 120
    limiter.check_transcript_read(ip="late")
    assert len(limiter._reads) < 4200


# ── HTTP input bounds ──────────────────────────────────────────────────────


def test_create_refuses_an_oversized_body() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    with TestClient(app) as client:
        resp = client.post(
            "/matches",
            content=b'{"game_id": "tictactoe", "pad": "' + b"x" * 100_000 + b'"}',
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "request_too_large"


@pytest.mark.parametrize(
    "players",
    [[{"label": "a"}, {"label": "b"}, {"label": "c"}], [{"label": "x" * 65}]],
)
def test_create_bounds_players_and_labels(players: list) -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    with TestClient(app) as client:
        resp = client.post("/matches", json={**_MATCH, "players": players})
    assert resp.status_code == 400


def test_a_rate_limited_client_is_refused_before_its_body_is_read() -> None:
    app = create_app(rate_limiter=RateLimiter(max_match_creations_per_ip_per_min=1))
    with TestClient(app) as client:
        assert client.post("/matches", json=_MATCH).status_code == 201
        resp = client.post("/matches", content=b"not even json")
    assert resp.status_code == 429


# ── Close codes (protocol sections 3 and 9) ──────────────────────────────


def test_a_binary_hello_closes_1003() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    with TestClient(app) as client:
        match_id = client.post("/matches", json=_MATCH).json()["match_id"]
        with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws:
            ws.send_bytes(b"\x00\x01")
            assert _close_code(ws) == 1003


def test_an_unknown_websocket_endpoint_closes_4404() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    with TestClient(app) as client:
        with client.websocket_connect("/nowhere/at/all") as ws:
            assert _close_code(ws) == 4404


def test_a_resume_token_for_the_other_seat_closes_4401() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    registry: MatchRegistry = app.state.match_registry
    with TestClient(app) as client:
        match_id = client.post("/matches", json=_MATCH).json()["match_id"]
        registry.get(match_id).resume_tokens[0] = "seat-zero-token"
        with client.websocket_connect(f"/matches/{match_id}/play?seat=1") as ws:
            ws.send_text(_hello(1, token="seat-zero-token"))
            assert _close_code(ws) == 4401


def test_a_stale_resume_token_closes_4410() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    registry: MatchRegistry = app.state.match_registry
    with TestClient(app) as client:
        match_id = client.post("/matches", json=_MATCH).json()["match_id"]
        registry.get(match_id).resume_tokens[0] = "current"
        with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws:
            ws.send_text(_hello(0, token="rotated-away"))
            assert _close_code(ws) == 4410


# ── Eviction wakes whoever waits on an evicted match ───────────────────────


def test_evicting_an_unstarted_match_closes_its_waiting_seat() -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    registry: MatchRegistry = app.state.match_registry
    with TestClient(app) as client:
        match_id = client.post("/matches", json=_MATCH).json()["match_id"]
        with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws:
            ws.send_text(_hello(0))
            assert "welcome" in ws.receive_text()
            registry._unstarted_max_age_s = 0.0  # everything unstarted has expired
            client.post("/matches", json=_MATCH)  # a create sweeps
            assert _close_code(ws) == 4410
        assert match_id not in app.state._ws_seat_slots


# ── The spectator welcome is serialised once per match state ───────────────


def test_repeated_spectator_attaches_reuse_the_serialised_welcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import arena.server.runtime_bridge as bridge

    built = 0
    real_dumps = bridge.dumps

    def counting(envelope: Any) -> str:
        nonlocal built
        if envelope.type == "spectator_welcome":
            built += 1
        return real_dumps(envelope)

    monkeypatch.setattr(bridge, "dumps", counting)
    app = create_app(rate_limiter=RateLimiter.unlimited())
    spectator_hello = (
        '{"type": "spectator_hello", "schema_version": 3, "payload": '
        '{"client_name": "t", "client_version": "0", "supported_schema_versions": [3]}}'
    )
    with TestClient(app) as client:
        match_id = client.post("/matches", json=_MATCH).json()["match_id"]
        texts = []
        for _ in range(3):
            with client.websocket_connect(f"/matches/{match_id}/spectate") as ws:
                ws.send_text(spectator_hello)
                texts.append(ws.receive_text())
    assert built == 1
    assert texts[0] == texts[1] == texts[2]
