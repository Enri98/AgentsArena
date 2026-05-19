"""Unit tests for Session via LocalSession proxy — no real network needed."""
from __future__ import annotations

import pytest

from arena.sdk._connect import _run_session
from arena.sdk.errors import MatchAbortedError
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


def _always_choose(obs: object) -> dict:
    """A simple choose() callback that always plays column 0."""
    return {"column": 0}


# ---------------------------------------------------------------------------
# _run_session tests (via LocalSession)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_run_session_single_obs_returns_result_and_transcript() -> None:
    """Single obs → action → match_finished returns (result, transcript)."""
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
    result, transcript = await _run_session(session, _always_choose)

    assert result["kind"] == "win"
    assert result["winner_seat"] == 0
    assert transcript is not None


@pytest.mark.anyio
async def test_run_session_sends_action_after_observation() -> None:
    """_run_session() calls choose() and sends an action for each ObservationEvent."""
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
    await _run_session(session, lambda obs: {"column": 3})
    assert session.sent_actions == [{"column": 3}]


@pytest.mark.anyio
async def test_run_session_match_aborted_raises_match_aborted_error() -> None:
    """obs → action → match_aborted raises MatchAbortedError."""
    script = [
        make_obs_envelope(seat=0),
        make_match_aborted_envelope(reason="peer_disconnected"),
    ]
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=script,
    )
    with pytest.raises(MatchAbortedError) as exc_info:
        await _run_session(session, _always_choose)

    err = exc_info.value
    assert isinstance(err, MatchAbortedError)
    assert err.abort_body is not None
    assert err.transcript is not None


@pytest.mark.anyio
async def test_run_session_drains_match_state_silently() -> None:
    """match_state envelopes are consumed without calling choose() or sending actions."""
    script = [
        make_match_state_envelope(lifecycle="running"),
        make_match_state_envelope(lifecycle="running"),
        make_obs_envelope(seat=0),
        make_match_finished_envelope(winner_seat=1),
    ]
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=script,
    )
    result, _ = await _run_session(session, _always_choose)
    # Only one action sent (for the observation), match_state frames were silent
    assert len(session.sent_actions) == 1
    assert result["winner_seat"] == 1


@pytest.mark.anyio
async def test_run_session_drains_turn_committed_silently() -> None:
    """turn_committed envelopes are consumed without calling choose() or sending actions."""
    script = [
        make_obs_envelope(seat=0),
        make_turn_committed_envelope(),
        make_match_finished_envelope(winner_seat=0),
    ]
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=script,
    )
    result, _ = await _run_session(session, _always_choose)
    assert len(session.sent_actions) == 1
    assert result["winner_seat"] == 0


@pytest.mark.anyio
async def test_run_session_multi_turn_match() -> None:
    """_run_session drives a multi-turn match (multiple observations)."""
    actions_sent: list[dict] = []
    call_count = 0

    def choose(obs: object) -> dict:
        nonlocal call_count
        call_count += 1
        action = {"column": call_count - 1}
        actions_sent.append(action)
        return action

    script = [
        make_obs_envelope(seat=0, turn_index=0),
        make_turn_committed_envelope(),
        make_match_state_envelope(),
        make_obs_envelope(seat=0, turn_index=1),
        make_turn_committed_envelope(),
        make_obs_envelope(seat=0, turn_index=2),
        make_match_finished_envelope(winner_seat=0),
    ]
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=script,
    )
    result, _ = await _run_session(session, choose)

    assert call_count == 3
    assert session.sent_actions == [{"column": 0}, {"column": 1}, {"column": 2}]
    assert result["winner_seat"] == 0


@pytest.mark.anyio
async def test_run_session_returns_correct_winner_seat() -> None:
    """Result contains correct winner_seat from the match_finished envelope."""
    for winner in (0, 1):
        script = [make_obs_envelope(seat=0), make_match_finished_envelope(winner_seat=winner)]
        session = LocalSession(
            match_id=MATCH_ID,
            game_id=GAME_ID,
            seat=0,
            server_script=script,
        )
        result, _ = await _run_session(session, _always_choose)
        assert result["winner_seat"] == winner


@pytest.mark.anyio
async def test_run_session_aborted_without_obs() -> None:
    """match_aborted without any prior obs raises MatchAbortedError immediately."""
    script = [make_match_aborted_envelope(reason="server_error")]
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=script,
    )
    with pytest.raises(MatchAbortedError):
        await _run_session(session, _always_choose)


@pytest.mark.anyio
async def test_run_session_mixed_drain_then_obs() -> None:
    """Multiple interleaved match_state/turn_committed frames before obs work correctly."""
    script = [
        make_match_state_envelope(),
        make_turn_committed_envelope(),
        make_match_state_envelope(),
        make_obs_envelope(seat=0),
        make_match_state_envelope(),
        make_match_finished_envelope(winner_seat=0),
    ]
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=script,
    )
    result, _ = await _run_session(session, _always_choose)
    assert len(session.sent_actions) == 1
    assert result["kind"] == "win"
