"""Retry-budget exhaustion over a real WebSocket (protocol §8.6 close ordering).

Ported from `tests/unit/server/test_routes_ws.py` in Phase 36 Slice 2. The
original drove two WebSocket sessions through a single Starlette TestClient
portal, and its own docstring documented an empirically-tuned send/drain order
to dodge portal deadlocks ("send BOTH illegal actions first, then drain").
That harness deadlocked nondeterministically and made the whole suite flaky.

Two real sockets against a real uvicorn server have no shared portal, so the
messages can be read in the order the protocol actually specifies.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx

from arena.adapters.in_process import ActionResponsePayload
from arena.adapters.websocket.envelope import ActionResponseEnvelope, HelloEnvelope
from arena.adapters.websocket.messages import ActionResponseBody, HelloBody
from tests.integration._ws_client import connect, recv_envelope, send_envelope
from tests.integration.conftest import RunningServer


def _hello(seat: int) -> HelloEnvelope:
    return HelloEnvelope(
        schema_version=1,
        seat=seat,
        payload=HelloBody(
            client_name="test",
            client_version="0.1.0",
            supported_schema_versions=[1, 2],
            auth=None,
            requested_seat=seat,
            resume_token=None,
        ),
    )


def _illegal_action(seat: int) -> ActionResponseEnvelope:
    """Column 99 is off the board for every supported Connect 4 config."""

    return ActionResponseEnvelope(
        schema_version=1,
        seat=seat,
        turn_id=str(uuid.uuid4()),
        payload=ActionResponseBody(
            action_response=ActionResponsePayload(
                game_id="connect4",
                schema_version=1,
                seat=seat,
                action={"column": 99},
            )
        ),
    )


def _create_match(http_base: str, **extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"game_id": "connect4", **extra}
    resp = httpx.post(f"{http_base}/matches", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_retry_budget_exhaustion_aborts_with_documented_ordering(
    running_server: RunningServer,
) -> None:
    """With `per_action_retry_budget=1`, two illegal actions abort the match.

    Attempt 1 decrements the budget to 0 and answers `action_rejected`.
    Attempt 2 finds no budget left and terminates, in the order protocol §8.6
    fixes: `action_rejected(0)` -> `match_state(aborted)` -> `match_aborted`.
    """

    async def run() -> None:
        match = _create_match(
            running_server.http_base_url,
            per_action_retry_budget=1,
            per_turn_deadline_ms=10_000,
        )

        async with (
            await connect(match["seat_0_url"]) as ws0,
            await connect(match["seat_1_url"]) as ws1,
        ):
            await send_envelope(ws0, _hello(0))
            assert (await recv_envelope(ws0)).type == "welcome"
            await send_envelope(ws1, _hello(1))
            assert (await recv_envelope(ws1)).type == "welcome"

            # Match starts: both seats get match_state(running); only the active
            # seat gets the observation_request.
            assert (await recv_envelope(ws0)).type == "match_state"
            assert (await recv_envelope(ws1)).type == "match_state"
            assert (await recv_envelope(ws0)).type == "observation_request"

            # Attempt 1: rejected, budget spent.
            await send_envelope(ws0, _illegal_action(0))
            rejected_1 = await recv_envelope(ws0)
            assert rejected_1.type == "action_rejected"
            assert rejected_1.payload.retries_remaining == 0

            # Attempt 2: no budget left -> terminate.
            await send_envelope(ws0, _illegal_action(0))

            rejected_2 = await recv_envelope(ws0)
            assert rejected_2.type == "action_rejected"
            assert rejected_2.payload.retries_remaining == 0

            state_0 = await recv_envelope(ws0)
            assert state_0.type == "match_state"
            assert state_0.payload.lifecycle == "aborted"

            aborted_0 = await recv_envelope(ws0)
            assert aborted_0.type == "match_aborted"

            # The off-turn seat sees the abort but never an action_rejected —
            # that is addressed to the active seat only (§18 broadcast matrix).
            state_1 = await recv_envelope(ws1)
            assert state_1.type == "match_state"
            assert state_1.payload.lifecycle == "aborted"

            aborted_1 = await recv_envelope(ws1)
            assert aborted_1.type == "match_aborted"

    asyncio.run(asyncio.wait_for(run(), timeout=30))
