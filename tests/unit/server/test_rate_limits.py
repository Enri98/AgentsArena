"""Protocol §13 rate limits: the RateLimiter itself, and its two wire surfaces.

§13 was specified from Phase 27 but unimplemented until Phase 36 Slice 0.  The
spectator endpoint is an unauthenticated fan-out primitive, so the caps had to
land before it opened.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from arena.server.app import create_app
from arena.server.rate_limits import (
    CLOSE_RATE_LIMITED,
    RateLimiter,
    RateLimitExceeded,
)

#: Matches here are created but never played. At the 30 s production per-turn
#: default an abandoned match parks run_match for 30 s, and those leaked drivers
#: made the suite flaky. Phase 36 Slice 2's match-owned driver is the real fix.
_SHORT_MATCH = {
    "game_id": "connect4",
    "per_turn_deadline_ms": 2000,
    "disconnect_grace_ms": 500,
}


# ---------------------------------------------------------------------------
# Unit: the limiter
# ---------------------------------------------------------------------------


class _Clock:
    """Manually advanced monotonic clock for sliding-window assertions."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def test_connections_per_ip_cap() -> None:
    limiter = RateLimiter(max_ws_connections_per_ip=2, max_connections_per_match=99)

    limiter.acquire_connection(ip="1.2.3.4", match_id="m1")
    limiter.acquire_connection(ip="1.2.3.4", match_id="m2")

    with pytest.raises(RateLimitExceeded) as exc:
        limiter.acquire_connection(ip="1.2.3.4", match_id="m3")
    assert exc.value.scope == "connections_per_ip"

    # A different address is unaffected.
    limiter.acquire_connection(ip="5.6.7.8", match_id="m3")


def test_connections_per_match_cap() -> None:
    limiter = RateLimiter(max_ws_connections_per_ip=99, max_connections_per_match=2)

    limiter.acquire_connection(ip="a", match_id="m1")
    limiter.acquire_connection(ip="b", match_id="m1")

    with pytest.raises(RateLimitExceeded) as exc:
        limiter.acquire_connection(ip="c", match_id="m1")
    assert exc.value.scope == "connections_per_match"

    # A different match is unaffected.
    limiter.acquire_connection(ip="c", match_id="m2")


def test_rejected_acquire_reserves_nothing() -> None:
    """A rejected acquire must not consume the other dimension's slot."""

    limiter = RateLimiter(max_ws_connections_per_ip=99, max_connections_per_match=1)
    limiter.acquire_connection(ip="a", match_id="m1")

    with pytest.raises(RateLimitExceeded):
        limiter.acquire_connection(ip="b", match_id="m1")

    assert limiter.connection_count(ip="b") == 0


def test_release_frees_a_slot_and_never_goes_negative() -> None:
    limiter = RateLimiter(max_ws_connections_per_ip=1, max_connections_per_match=99)

    limiter.acquire_connection(ip="a", match_id="m1")
    with pytest.raises(RateLimitExceeded):
        limiter.acquire_connection(ip="a", match_id="m2")

    limiter.release_connection(ip="a", match_id="m1")
    limiter.acquire_connection(ip="a", match_id="m2")  # slot freed

    # Over-releasing is safe and does not create negative headroom.
    for _ in range(5):
        limiter.release_connection(ip="a", match_id="m2")
    assert limiter.connection_count(ip="a") == 0


def test_match_creation_sliding_window() -> None:
    clock = _Clock()
    limiter = RateLimiter(max_match_creations_per_ip_per_min=2, time_fn=clock)

    limiter.check_match_creation(ip="a")
    limiter.check_match_creation(ip="a")
    with pytest.raises(RateLimitExceeded) as exc:
        limiter.check_match_creation(ip="a")
    assert exc.value.scope == "match_creations_per_ip"

    # Still capped just inside the window.
    clock.advance(59.0)
    with pytest.raises(RateLimitExceeded):
        limiter.check_match_creation(ip="a")

    # The first two fall out of the trailing window.
    clock.advance(2.0)
    limiter.check_match_creation(ip="a")


def test_action_window() -> None:
    clock = _Clock()
    limiter = RateLimiter(max_actions_per_match_per_sec=2, time_fn=clock)

    limiter.check_action(match_id="m1")
    limiter.check_action(match_id="m1")
    with pytest.raises(RateLimitExceeded) as exc:
        limiter.check_action(match_id="m1")
    assert exc.value.scope == "actions_per_match"

    clock.advance(1.1)
    limiter.check_action(match_id="m1")


def test_forget_match_clears_per_match_state() -> None:
    limiter = RateLimiter(max_connections_per_match=1, max_actions_per_match_per_sec=1)
    limiter.acquire_connection(ip="a", match_id="m1")
    limiter.check_action(match_id="m1")

    limiter.forget_match("m1")

    assert limiter.connection_count(match_id="m1") == 0
    limiter.acquire_connection(ip="b", match_id="m1")
    limiter.check_action(match_id="m1")


def test_unlimited_is_permissive() -> None:
    limiter = RateLimiter.unlimited()
    for i in range(50):
        limiter.acquire_connection(ip="a", match_id="m1")
        limiter.check_match_creation(ip="a")
        limiter.check_action(match_id="m1")
    assert limiter.connection_count(match_id="m1") == 50


# ---------------------------------------------------------------------------
# Wire surface: HTTP 429 on match creation (protocol §9)
# ---------------------------------------------------------------------------


def test_match_creation_cap_returns_429() -> None:
    app = create_app(rate_limiter=RateLimiter(max_match_creations_per_ip_per_min=3))
    with TestClient(app, raise_server_exceptions=False) as client:
        for _ in range(3):
            assert client.post("/matches", json=_SHORT_MATCH).status_code == 201

        resp = client.post("/matches", json=_SHORT_MATCH)
        assert resp.status_code == 429
        assert resp.json()["error"]["code"] == "rate_limited"


def test_match_creation_cap_does_not_affect_reads() -> None:
    app = create_app(rate_limiter=RateLimiter(max_match_creations_per_ip_per_min=1))
    with TestClient(app, raise_server_exceptions=False) as client:
        match_id = client.post("/matches", json=_SHORT_MATCH).json()["match_id"]
        assert client.post("/matches", json=_SHORT_MATCH).status_code == 429

        assert client.get("/games").status_code == 200
        assert client.get(f"/matches/{match_id}").status_code == 200


# ---------------------------------------------------------------------------
# Wire surface: WebSocket close 4429 (protocol §9)
# ---------------------------------------------------------------------------


def _hello(seat: int) -> dict[str, Any]:
    return {
        "type": "hello",
        "schema_version": 1,
        "seat": seat,
        "payload": {
            "client_name": "test-client",
            "client_version": "0.1.0",
            "supported_schema_versions": [1],
            "auth": None,
            "requested_seat": seat,
            "resume_token": None,
        },
    }


def test_connection_cap_closes_with_4429() -> None:
    """An over-cap connection is closed with 4429, not 4409 (seat_taken).

    The cap is deliberately 1 so only seat 0 connects: a test that fills both
    seats would start run_match, and abandoning a running match makes the
    TestClient shutdown block until the per-turn deadline expires.
    """

    app = create_app(
        rate_limiter=RateLimiter(
            max_ws_connections_per_ip=99,
            max_connections_per_match=1,
            max_match_creations_per_ip_per_min=99,
        )
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        match_id = client.post("/matches", json=_SHORT_MATCH).json()["match_id"]

        with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws0:
            ws0.send_text(json.dumps(_hello(0)))
            assert json.loads(ws0.receive_text())["type"] == "welcome"

            # The only slot is taken: seat 1 is shed by the §13 cap before it
            # ever reaches the seat-occupancy check that would answer 4409.
            with client.websocket_connect(f"/matches/{match_id}/play?seat=1") as ws1:
                with pytest.raises(WebSocketDisconnect) as exc:
                    ws1.receive_text()
                assert exc.value.code == CLOSE_RATE_LIMITED


def test_released_slot_is_reusable() -> None:
    """Closing a connection returns its slot to the per-match pool."""

    limiter = RateLimiter(
        max_ws_connections_per_ip=99,
        max_connections_per_match=1,
        max_match_creations_per_ip_per_min=99,
    )
    with TestClient(create_app(rate_limiter=limiter), raise_server_exceptions=False) as client:
        match_id = client.post("/matches", json=_SHORT_MATCH).json()["match_id"]

        with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws0:
            ws0.send_text(json.dumps(_hello(0)))
            assert json.loads(ws0.receive_text())["type"] == "welcome"

    assert limiter.connection_count(match_id=match_id) == 0
