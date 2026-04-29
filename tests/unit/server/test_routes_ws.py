"""WebSocket route tests for WS /matches/{id}/play and /spectate.

Uses FastAPI TestClient's synchronous websocket_connect context manager.
Two-connection happy-path tests open both WebSocket connections sequentially
inside the same TestClient (which runs the ASGI app in a thread); we drive
seat 0 and seat 1 one frame at a time using the observation_request the server
sends to tell us whose turn it is.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from arena.games import build_default_registry
from arena.runtime.payloads import validate_runtime_transcript
from arena.server.app import create_app

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


def _action_response(game_id: str, seat: int, action: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "action_response",
        "schema_version": 1,
        "turn_id": str(uuid.uuid4()),
        "seat": seat,
        "payload": {
            "action_response": {
                "game_id": game_id,
                "schema_version": 1,
                "seat": seat,
                "action": action,
            }
        },
    }


def _client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


def _post_match(client: TestClient, game_id: str, **extra: Any) -> str:
    body: dict[str, Any] = {"game_id": game_id, **extra}
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


def _recv_one(ws, timeout: float = 5.0) -> dict[str, Any] | None:
    """Receive one message using a background thread to avoid blocking.

    The Starlette TestClient shares a single anyio portal across all WS sessions.
    We use a background thread so the calling thread can impose a timeout without
    permanently blocking on portal.call.
    """
    import threading

    result: list[Any] = [None, None]  # [value, error]

    def go() -> None:
        try:
            result[0] = ws.receive_json()
        except Exception as exc:
            result[1] = exc

    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        return None  # timed out
    if result[1] is not None:
        raise result[1]
    return result[0]


def _recv(ws) -> dict[str, Any]:
    """Direct blocking receive — use only inside _play_full_match where drain order is correct."""
    return ws.receive_json()


def _play_full_match(
    client: TestClient,
    match_id: str,
    game_id: str,
    move_sequences: dict[int, list[Any]],
) -> dict[str, Any]:
    """Open both WS connections and play a complete match.

    Drain rule (empirically verified with the Starlette TestClient):
    After seat X sends an action, always drain ws_next (the NEXT-ACTIVE seat, 1-X)
    BEFORE draining ws_current (seat X).  This avoids TestClient portal deadlocks.

    The server sends: _broadcast(tc) → seat0, seat1; _broadcast(ms) → seat0, seat1;
    _send(obs) → next-active seat only.  Despite seat 0 receiving tc/ms first in each
    broadcast, draining seat 0 first deadlocks when seat 0 is the current (just-moved)
    seat; draining the next-active seat first always works.

    We carry obs_request from one iteration to the next (pending_obs) so we never
    consume a frame that the following iteration needs as its observation.

    Drain sequence after seat X acts (non-terminal):
      1. ws_next: turn_committed, match_state, obs_request  ← ws_next becomes next active
      2. ws_current: turn_committed, match_state

    Drain sequence after seat X acts (terminal):
      1. ws_next: turn_committed, match_state, match_finished/aborted
      2. ws_current: turn_committed, match_state, match_finished/aborted

    Uses direct blocking ws.receive_json() calls (no threading) so that closing the
    WebSocket connections on exit is not blocked by daemon threads holding the portal.
    """
    move_iters: dict[int, Any] = {seat: iter(moves) for seat, moves in move_sequences.items()}
    terminal: dict[str, Any] = {}
    TERMINAL_TYPES = ("match_finished", "match_aborted")

    with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws0:
        with client.websocket_connect(f"/matches/{match_id}/play?seat=1") as ws1:
            ws_map = {0: ws0, 1: ws1}

            # Handshake
            ws0.send_json(_hello(0))
            m = _recv(ws0)
            assert m["type"] == "welcome", f"s0 welcome: {m}"
            ws1.send_json(_hello(1))
            m = _recv(ws1)
            assert m["type"] == "welcome", f"s1 welcome: {m}"

            # run_match broadcasts match_state(running) to both seats, then sends
            # obs_request only to seat 0 (seat 0 always starts).
            # Drain ws0 (ms + obs) first, then ws1 (ms).
            ms0 = _recv(ws0)
            assert ms0["type"] == "match_state", f"s0 ms: {ms0}"
            obs0 = _recv(ws0)
            assert obs0["type"] == "observation_request", f"s0 obs: {obs0}"
            ms1 = _recv(ws1)
            assert ms1["type"] == "match_state", f"s1 ms: {ms1}"

            # Carry the first obs_request into the loop.
            pending_obs: dict[str, Any] = obs0

            for _ in range(200):
                obs_msg = pending_obs
                pending_obs = None  # type: ignore[assignment]

                if obs_msg["type"] in TERMINAL_TYPES:
                    terminal = obs_msg
                    break

                assert obs_msg["type"] == "observation_request", (
                    f"Expected obs_request, got {obs_msg['type']}"
                )

                obs = obs_msg["payload"]["observation_request"]
                current_seat: int = obs["seat"]
                ws_current = ws_map[current_seat]
                ws_next = ws_map[1 - current_seat]

                try:
                    raw_move = next(move_iters[current_seat])
                except StopIteration:
                    pytest.fail(f"Ran out of moves for seat {current_seat}")

                act = {"column": raw_move} if game_id == "connect4" else raw_move
                ws_current.send_json(_action_response(game_id, current_seat, act))

                # --- Drain ws_next FIRST ---
                tc_n = _recv(ws_next)
                if tc_n["type"] in TERMINAL_TYPES:
                    terminal = tc_n
                    _recv(ws_current)  # tc_current
                    _recv(ws_current)  # ms_current
                    _recv(ws_current)  # terminal_current
                    break

                ms_n = _recv(ws_next)
                assert ms_n["type"] == "match_state", f"ws_next expected match_state, got {ms_n}"
                lc_n = ms_n["payload"].get("lifecycle")
                if lc_n in ("finished", "aborted"):
                    # Terminal: next seat gets match_finished/aborted; drain current seat too.
                    term_n = _recv(ws_next)
                    _recv(ws_current)  # tc
                    _recv(ws_current)  # ms
                    term_c = _recv(ws_current)
                    terminal = (
                        term_c if term_c["type"] in TERMINAL_TYPES else
                        term_n if term_n["type"] in TERMINAL_TYPES else {}
                    )
                    break

                # Non-terminal: ws_next gets obs_request for the next turn.
                obs_next = _recv(ws_next)
                if obs_next["type"] in TERMINAL_TYPES:
                    terminal = obs_next
                    _recv(ws_current)  # tc
                    _recv(ws_current)  # ms
                    _recv(ws_current)  # terminal
                    break

                # --- Now drain ws_current: tc + ms ---
                tc_c = _recv(ws_current)
                if tc_c["type"] in TERMINAL_TYPES:
                    terminal = tc_c
                    break

                ms_c = _recv(ws_current)
                if ms_c.get("type") == "match_state":
                    lc_c = ms_c["payload"].get("lifecycle")
                    if lc_c in ("finished", "aborted"):
                        term_c = _recv(ws_current)
                        term_n = _recv(ws_next)
                        terminal = (
                            term_c if term_c["type"] in TERMINAL_TYPES else
                            term_n if term_n["type"] in TERMINAL_TYPES else {}
                        )
                        break

                # Carry obs_next to the next iteration.
                pending_obs = obs_next

            else:
                pytest.fail("Match did not terminate within 200 turns")

    return terminal


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


def test_connect4_happy_path_full_match() -> None:
    """Two scripted clients complete a Connect 4 match; transcript validates."""
    client = _client()
    match_id = _post_match(
        client,
        "connect4",
        players=[{"label": "alice"}, {"label": "bob"}],
        per_action_retry_budget=3,
    )
    terminal = _play_full_match(client, match_id, "connect4", CONNECT4_MOVES)
    assert terminal.get("type") in ("match_finished", "match_aborted"), terminal

    if terminal.get("type") == "match_finished":
        raw_transcript = terminal["payload"]["transcript"]
        registry = build_default_registry()
        definition = registry.get("connect4")
        loaded = validate_runtime_transcript(definition, raw_transcript)
        assert loaded is not None


def test_tictactoe_happy_path_full_match() -> None:
    """Two scripted clients complete a Tic-Tac-Toe match; transcript validates."""
    client = _client()
    match_id = _post_match(
        client,
        "tictactoe",
        players=[{"label": "x"}, {"label": "o"}],
    )
    terminal = _play_full_match(client, match_id, "tictactoe", TTT_MOVES)
    assert terminal.get("type") in ("match_finished", "match_aborted"), terminal

    if terminal.get("type") == "match_finished":
        raw_transcript = terminal["payload"]["transcript"]
        registry = build_default_registry()
        definition = registry.get("tictactoe")
        loaded = validate_runtime_transcript(definition, raw_transcript)
        assert loaded is not None


def test_malformed_envelope_after_welcome() -> None:
    """Sending garbage after the handshake should produce an error envelope, not a close.

    Starlette TestClient limitation: while the server has an active receive_text() pending
    on ws0 (waiting for the next action), the test cannot call ws0.receive_json() because
    both compete for the same portal.  Workaround: send a valid action immediately after
    the malformed one so the server processes both (error then tc+ms+obs), and then drain
    all pending frames from ws0 after the server's receive_text has been satisfied.
    """
    client = _client()
    match_id = _post_match(client, "connect4")

    with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws0:
        ws0.send_json(_hello(0))
        ws0.receive_json()  # welcome

        with client.websocket_connect(f"/matches/{match_id}/play?seat=1") as ws1:
            ws1.send_json(_hello(1))
            ws1.receive_json()  # welcome

            # Drain initial state: ws0(ms, obs), ws1(ms)
            ws0.receive_json()   # match_state running
            obs_msg = ws0.receive_json()  # obs_request
            ws1.receive_json()   # match_state running
            assert obs_msg["type"] == "observation_request"

            # Send malformed JSON, then immediately a valid action.
            # The server processes malformed → sends error envelope to ws0.
            # Then processes the valid action → sends tc(ws1), ms(ws1), obs(ws0? no,
            # seat 1 is next) and tc(ws0), ms(ws0).
            ws0.send_text("}{not valid json")
            ws0.send_json(_action_response("connect4", 0, {"column": 0}))

            # The server sends error to ws0, then processes the valid action.
            # After the valid action: _broadcast(tc) → ws1 first because that's next-active,
            # then ws0.  _broadcast(ms) same.  _send(obs) → ws1.
            # But we need to satisfy portal order: drain ws1(tc,ms,obs) first, then ws0.
            # However ws0 also gets error + tc + ms.
            # Actual order the server sends to ws0: error, tc, ms  (from broadcast after valid)
            # Actual order the server sends to ws1: tc, ms, obs
            # Portal drain: ws1(tc), ws1(ms), ws1(obs), ws0(error), ws0(tc), ws0(ms)
            ws1.receive_json()  # tc to ws1
            ws1.receive_json()  # ms to ws1
            ws1.receive_json()  # obs to ws1

            err_msg = ws0.receive_json()  # error to ws0
            assert err_msg["type"] == "error", f"expected error, got {err_msg['type']}"
            assert err_msg["payload"]["code"] == "malformed_envelope"
            ws0.receive_json()  # tc to ws0
            ws0.receive_json()  # ms to ws0


def test_illegal_action_retry_budget_exhaustion() -> None:
    """Retry budget exhaustion follows §8.6 termination ordering.

    With per_action_retry_budget=1:
      Attempt 1: retries_left=1 → not 0 → decrement to 0 → action_rejected(retries_remaining=0)
      Attempt 2: retries_left=0 → abort: action_rejected(0) + match_state(aborted) + match_aborted

    Starlette TestClient portal constraint: after each illegal send the server immediately
    awaits receive_text on ws0, so we cannot drain ws0 yet.  We send BOTH illegal actions
    first, then drain.  The server processes them in sequence: for attempt 1 it sends
    action_rejected(0) to ws0 and loops; for attempt 2 it sends action_rejected(0) +
    match_state(aborted) + match_aborted to ws0/ws1 and closes.

    After the close, the portal is free and we can drain.  We drain ws1 first (next-active
    rule), then ws0.
    """
    client = _client()
    match_id = _post_match(
        client,
        "connect4",
        per_action_retry_budget=1,  # 1 retry → 2 total attempts before abort
    )

    with client.websocket_connect(f"/matches/{match_id}/play?seat=0") as ws0:
        ws0.send_json(_hello(0))
        ws0.receive_json()  # welcome

        with client.websocket_connect(f"/matches/{match_id}/play?seat=1") as ws1:
            ws1.send_json(_hello(1))
            ws1.receive_json()  # welcome

            # Drain initial: ws0(ms, obs), ws1(ms)
            ws0.receive_json()  # match_state running
            obs_msg = ws0.receive_json()  # obs_request
            ws1.receive_json()  # match_state running
            assert obs_msg["type"] == "observation_request"

            illegal = _action_response("connect4", 0, {"column": 99})

            # Send both illegal actions before draining — avoids portal deadlock.
            ws0.send_json(illegal)
            ws0.send_json({**illegal, "turn_id": str(uuid.uuid4())})

            # Drain ws1 first (abort broadcast: ms(aborted) + match_aborted + close).
            # ws1 does NOT get action_rejected (that's only to the active seat, ws0).
            ms_abort_ws1 = ws1.receive_json()
            assert ms_abort_ws1["type"] == "match_state", f"ws1: {ms_abort_ws1}"
            assert ms_abort_ws1["payload"]["lifecycle"] == "aborted"
            term_ws1 = ws1.receive_json()
            assert term_ws1["type"] == "match_aborted", f"ws1 term: {term_ws1}"
            # Connection closes after match_aborted.
            with pytest.raises(Exception):
                ws1.receive_json()

            # Now drain ws0: action_rejected(0) from attempt 1, then
            # action_rejected(0) + match_state(aborted) + match_aborted from attempt 2.
            rej1 = ws0.receive_json()
            assert rej1["type"] == "action_rejected", f"ws0 first: {rej1}"
            assert rej1["payload"]["retries_remaining"] == 0

            rej2 = ws0.receive_json()
            assert rej2["type"] == "action_rejected", f"ws0 second: {rej2}"
            assert rej2["payload"]["retries_remaining"] == 0

            ms_abort_ws0 = ws0.receive_json()
            assert ms_abort_ws0["type"] == "match_state"
            assert ms_abort_ws0["payload"]["lifecycle"] == "aborted"

            term_ws0 = ws0.receive_json()
            assert term_ws0["type"] == "match_aborted"
            with pytest.raises(Exception):
                ws0.receive_json()
