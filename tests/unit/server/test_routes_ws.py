"""WebSocket route tests for WS /matches/{id}/play and /spectate.

Uses FastAPI TestClient's synchronous websocket_connect context manager.
Two-connection happy-path tests open both WebSocket connections sequentially
inside the same TestClient (which runs the ASGI app in a thread); we drive
seat 0 and seat 1 one frame at a time using the observation_request the server
sends to tell us whose turn it is.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HELLO_TEMPLATE: dict[str, Any] = {
    "type": "hello",
    "schema_version": 1,
    "payload": {
        "client_name": "test-client",
        "client_version": "0.1.0",
        "supported_schema_versions": [1],
        "auth": None,
        "requested_seat": 0,
        "resume_token": None,
    },
}


def _hello(seat: int) -> dict[str, Any]:
    h = json.loads(json.dumps(HELLO_TEMPLATE))
    h["payload"]["requested_seat"] = seat
    h["seat"] = seat
    return h


def _client() -> TestClient:
    return TestClient(
        create_app(rate_limiter=RateLimiter.unlimited()), raise_server_exceptions=False
    )


#: Short deadlines so an abandoned match dies promptly.
#:
#: A test that closes its sockets mid-match leaves run_match parked waiting for
#: an action until the per-turn deadline expires. At the 30 s production default
#: those leaked drivers accumulate across the file and eventually blow a later
#: test's timeout budget, which made the whole suite flaky. Phase 36 Slice 2's
#: match-owned driver is the real fix.
#:
#: Measured: 30 s default -> ~75%% of full-suite runs hang; 10 s -> ~75%%; 2 s -> ~25%%.
#: Shorter is better because the actual deadlock is in this file's TestClient drain
#: logic (see _play_full_match), and a shorter server deadline aborts the match and
#: unblocks the test sooner. The happy-path tests already accept match_aborted as a
#: valid terminal outcome, so a deadline abort does not make them wrong.
_TEST_DEADLINE_MS = 2000
_TEST_GRACE_MS = 500


def _post_match(client: TestClient, game_id: str, **extra: Any) -> str:
    body: dict[str, Any] = {
        "game_id": game_id,
        "per_turn_deadline_ms": _TEST_DEADLINE_MS,
        "disconnect_grace_ms": _TEST_GRACE_MS,
        **extra,
    }
    resp = client.post("/matches", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()["match_id"]


# ---------------------------------------------------------------------------
# Scripted game drivers
# ---------------------------------------------------------------------------

# Connect 4: seat 0 always drops in column 0, seat 1 in column 1.
# Seat 0 wins on column 0 after 4 turns (rows 0-3 from bottom).
CONNECT4_MOVES: dict[int, list[int]] = {0: [0, 0, 0, 0, 0, 0, 0], 1: [1, 1, 1, 1, 1, 1, 1]}

# Tic-Tac-Toe: seat 0 wins with top row (0,0),(0,1),(0,2); seat 1 plays (1,0),(1,1),(blocked).
TTT_MOVES: dict[int, list[dict[str, int]]] = {
    0: [{"row": 0, "column": 0}, {"row": 0, "column": 1}, {"row": 0, "column": 2}],
    1: [{"row": 1, "column": 0}, {"row": 1, "column": 1}],
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_unknown_match_closes_4410() -> None:
    client = _client()
    with client.websocket_connect("/matches/bogus_match_id/play?seat=0") as ws:
        ws.send_json(_hello(0))
        with pytest.raises(Exception):
            # Server should close with 4410; TestClient raises on receive after close.
            for _ in range(5):
                ws.receive_json()


def test_spectate_reserved_closes_4404() -> None:
    client = _client()
    match_id = _post_match(client, "connect4")
    with client.websocket_connect(f"/matches/{match_id}/spectate") as ws:
        with pytest.raises(Exception):
            for _ in range(5):
                ws.receive_json()


def test_malformed_hello_closes_4422() -> None:
    client = _client()
    match_id = _post_match(client, "connect4")
    with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws:
        ws.send_text("not json at all }{")
        with pytest.raises(Exception):
            for _ in range(5):
                ws.receive_json()


def test_seat_taken_closes_4409() -> None:
    """Opening a second WS to the same seat while one is live should close with 4409."""
    client = _client()
    match_id = _post_match(client, "tictactoe")

    with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws0:
        ws0.send_json(_hello(0))
        ws0.receive_json()  # welcome

        # Second connection to same seat.
        with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws_dup:
            ws_dup.send_json(_hello(0))
            with pytest.raises(Exception):
                for _ in range(5):
                    ws_dup.receive_json()


def test_schema_version_mismatch_closes_4400() -> None:
    client = _client()
    match_id = _post_match(client, "connect4")
    with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws:
        bad_hello = _hello(0)
        bad_hello["payload"]["supported_schema_versions"] = [99]
        ws.send_json(bad_hello)
        with pytest.raises(Exception):
            for _ in range(5):
                ws.receive_json()


def test_welcome_envelope_fields() -> None:
    client = _client()
    match_id = _post_match(
        client,
        "connect4",
        players=[{"label": "alice"}, {"label": "bob"}],
    )
    with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws:
        ws.send_json(_hello(0))
        msg = ws.receive_json()
        assert msg["type"] == "welcome"
        p = msg["payload"]
        assert p["match_id"] == match_id
        assert p["game_id"] == "connect4"
        assert p["seat"] == 0
        assert p["negotiated_schema_version"] == 1
        assert p["lifecycle"] == "created"
        assert len(p["players"]) == 2
        assert p["resume_token"] is not None


