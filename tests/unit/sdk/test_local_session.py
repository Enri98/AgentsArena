"""Unit tests for LocalSession."""
from __future__ import annotations

import pytest

from arena.sdk._events import (
    MatchAbortedEvent,
    MatchFinishedEvent,
    MatchStateEvent,
    ObservationEvent,
    TurnCommittedEvent,
)
from arena.sdk.testing import LocalSession
from tests.unit.sdk.conftest import (
    GAME_ID,
    MATCH_ID,
    make_match_aborted_envelope,
    make_match_finished_envelope,
    make_match_state_envelope,
    make_obs_envelope,
    make_turn_committed_envelope,
)


@pytest.mark.anyio
async def test_local_session_recv_returns_events_in_order() -> None:
    """recv() returns events from the script in insertion order."""
    script = [
        make_obs_envelope(seat=0),
        make_match_finished_envelope(winner_seat=0),
    ]
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=script,
    )
    event1 = await session.recv()
    event2 = await session.recv()
    assert isinstance(event1, ObservationEvent)
    assert isinstance(event2, MatchFinishedEvent)


@pytest.mark.anyio
async def test_local_session_recv_raises_stop_async_iteration_when_exhausted() -> None:
    """recv() raises StopAsyncIteration when the script is empty."""
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=[],
    )
    with pytest.raises(StopAsyncIteration):
        await session.recv()


@pytest.mark.anyio
async def test_local_session_recv_raises_stop_async_iteration_after_all_consumed() -> None:
    """recv() raises StopAsyncIteration once all scripted envelopes are consumed."""
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=[make_obs_envelope()],
    )
    await session.recv()
    with pytest.raises(StopAsyncIteration):
        await session.recv()


@pytest.mark.anyio
async def test_local_session_send_action_records_action() -> None:
    """send_action() records actions accessible via sent_actions."""
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=[],
    )
    assert session.sent_actions == []
    await session.send_action({"column": 3})
    assert session.sent_actions == [{"column": 3}]


@pytest.mark.anyio
async def test_local_session_send_action_records_multiple_actions() -> None:
    """send_action() records all actions in order."""
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=[],
    )
    await session.send_action({"column": 0})
    await session.send_action({"column": 6})
    await session.send_action({"row": 1, "col": 2})
    assert session.sent_actions == [{"column": 0}, {"column": 6}, {"row": 1, "col": 2}]


@pytest.mark.anyio
async def test_local_session_send_action_records_turn_ids() -> None:
    """send_action() with explicit turn_id records it in sent_turn_ids."""
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=[],
    )
    await session.send_action({"column": 2}, turn_id="my-turn-id")
    assert "my-turn-id" in session.sent_turn_ids


@pytest.mark.anyio
async def test_local_session_send_action_generates_turn_id_when_not_provided() -> None:
    """send_action() without turn_id generates a UUID."""
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=[],
    )
    await session.send_action({"column": 4})
    assert len(session.sent_turn_ids) == 1
    assert len(session.sent_turn_ids[0]) > 0


@pytest.mark.anyio
async def test_local_session_sent_actions_returns_copy() -> None:
    """sent_actions returns a copy, not the internal list."""
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=[],
    )
    await session.send_action({"column": 1})
    actions = session.sent_actions
    actions.append({"column": 99})
    assert session.sent_actions == [{"column": 1}]


@pytest.mark.anyio
async def test_local_session_properties() -> None:
    """LocalSession exposes match_id, seat, game_id, and welcome properties."""
    session = LocalSession(
        match_id="my-match",
        game_id="tictactoe",
        seat=1,
        server_script=[],
    )
    assert session.match_id == "my-match"
    assert session.seat == 1
    assert session.game_id == "tictactoe"
    assert session.welcome.match_id == "my-match"
    assert session.welcome.seat == 1
    assert session.welcome.game_id == "tictactoe"


@pytest.mark.anyio
async def test_local_session_context_manager() -> None:
    """LocalSession works as an async context manager."""
    script = [make_obs_envelope(), make_match_finished_envelope()]
    async with LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=script,
    ) as session:
        event = await session.recv()
        assert isinstance(event, ObservationEvent)


@pytest.mark.anyio
async def test_local_session_match_state_event() -> None:
    """recv() converts match_state envelope to MatchStateEvent."""
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=[make_match_state_envelope()],
    )
    event = await session.recv()
    assert isinstance(event, MatchStateEvent)


@pytest.mark.anyio
async def test_local_session_turn_committed_event() -> None:
    """recv() converts turn_committed envelope to TurnCommittedEvent."""
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=[make_turn_committed_envelope()],
    )
    event = await session.recv()
    assert isinstance(event, TurnCommittedEvent)


@pytest.mark.anyio
async def test_local_session_match_aborted_event() -> None:
    """recv() converts match_aborted envelope to MatchAbortedEvent."""
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=[make_match_aborted_envelope()],
    )
    event = await session.recv()
    assert isinstance(event, MatchAbortedEvent)


@pytest.mark.anyio
async def test_local_session_observation_event_body_fields() -> None:
    """ObservationEvent body has observation_request with correct seat."""
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=[make_obs_envelope(seat=0)],
    )
    event = await session.recv()
    assert isinstance(event, ObservationEvent)
    assert event.body.observation_request.seat == 0
    assert event.body.observation_request.game_id == GAME_ID
