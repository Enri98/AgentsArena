"""Tests for local match transcript dump/load helpers."""

from __future__ import annotations

import copy
import json

import pytest
from pydantic import ValidationError

from arena.core.exceptions import WrongPlayer
from arena.core.results import Win
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    Connect4GameDefinition,
    Connect4Observation,
    Connect4State,
    DropDisc,
)
from arena.match import (
    LoadedMatchTranscript,
    LocalMatch,
    apply_match_action,
    dump_match_transcript,
    load_match_transcript,
    start_match,
    validate_match_transcript,
)
from arena.match.transcript import MATCH_TRANSCRIPT_SCHEMA_VERSION


def _build_connect4_match() -> LocalMatch[
    Connect4Config,
    Connect4State,
    DropDisc,
    Connect4Observation,
    Win,
]:
    return start_match(Connect4GameDefinition, Connect4Config(rows=4, columns=4, connect_length=4))


def _play_connect4_win() -> LocalMatch[
    Connect4Config,
    Connect4State,
    DropDisc,
    Connect4Observation,
    Win,
]:
    match = _build_connect4_match()
    for column in (0, 1, 0, 1, 0, 1, 0):
        match = apply_match_action(
            match,
            match.rules_engine.current_seat(match.state),
            DropDisc(column=column),
        )
    return match


def _tamper_first_action(payload: dict[str, object]) -> None:
    payload["turns"][0]["action"] = {"column": 2}  # type: ignore[index]


def _tamper_first_post_snapshot_schema_version(payload: dict[str, object]) -> None:
    payload["turns"][0]["post_snapshot"]["schema_version"] = 99  # type: ignore[index]


def _tamper_first_event_row(payload: dict[str, object]) -> None:
    payload["turns"][0]["events"][0]["payload"]["row"] = 2  # type: ignore[index]


def _tamper_final_result_seat(payload: dict[str, object]) -> None:
    payload["turns"][-1]["result"]["payload"]["seat"] = 1  # type: ignore[index]


def _tamper_first_recorded_seat(payload: dict[str, object]) -> None:
    payload["turns"][0]["seat"] = 1  # type: ignore[index]


def test_dump_match_transcript_is_json_safe_for_an_ongoing_match() -> None:
    match = apply_match_action(
        _build_connect4_match(),
        0,
        DropDisc(column=0),
    )

    payload = dump_match_transcript(match)
    loaded = load_match_transcript(Connect4GameDefinition, payload)

    assert json.dumps(payload)
    assert payload["game_id"] == CONNECT4_GAME_ID
    assert payload["schema_version"] == MATCH_TRANSCRIPT_SCHEMA_VERSION
    assert payload["initial_snapshot"]["game_id"] == CONNECT4_GAME_ID
    assert payload["turns"][0]["action"] == {"column": 0}
    assert payload["turns"][0]["events"][0]["event_type"] == "DiscDropped"
    assert payload["turns"][0]["events"][0]["payload"] == {"seat": 0, "column": 0, "row": 3}
    assert payload["turns"][0]["result"] is None

    assert isinstance(loaded, LoadedMatchTranscript)
    assert loaded.definition is Connect4GameDefinition
    assert loaded.config == match.config
    assert loaded.initial_snapshot == match.initial_snapshot
    assert loaded.initial_state == _build_connect4_match().state
    assert loaded.latest_state == match.state
    assert len(loaded.turns) == 1
    assert loaded.turns[0].action == DropDisc(column=0)
    assert loaded.turns[0].post_state == match.state
    assert loaded.turns[0].post_snapshot == match.turns[0].post_snapshot
    expected_event_payload = {
        "event_type": "DiscDropped",
        "payload": {"seat": 0, "column": 0, "row": 3},
    }
    assert loaded.turns[0].event_payloads == (expected_event_payload,)
    assert loaded.turns[0].result is None
    assert loaded.turns[0].result_payload is None


def test_terminal_transcript_metadata_and_state_rehydration() -> None:
    match = _play_connect4_win()

    payload = dump_match_transcript(match)
    loaded = load_match_transcript(Connect4GameDefinition, payload)

    expected_event_payload = {
        "event_type": "WinnerDetected",
        "payload": {"winning_seat": 0},
    }
    expected_result_payload = {"result_type": "Win", "payload": {"seat": 0}}

    assert payload["turns"][-1]["events"][-1] == expected_event_payload
    assert payload["turns"][-1]["result"] == expected_result_payload

    assert loaded.latest_state == match.state
    assert loaded.turns[-1].post_state == match.state
    assert loaded.turns[-1].post_snapshot == match.turns[-1].post_snapshot
    assert loaded.turns[-1].event_payloads[-1] == expected_event_payload
    assert loaded.turns[-1].result == Win(seat=0)
    assert loaded.turns[-1].result_payload == expected_result_payload
    assert loaded.turns[-1].seat == 0


def test_validate_match_transcript_accepts_a_terminal_connect4_replay() -> None:
    match = _play_connect4_win()

    payload = dump_match_transcript(match)
    loaded = validate_match_transcript(Connect4GameDefinition, payload)

    assert isinstance(loaded, LoadedMatchTranscript)
    assert loaded.latest_state == match.state
    assert loaded.turns[-1].result == Win(seat=0)


@pytest.mark.parametrize(
    ("mutate", "expected_exception", "expected_message"),
    [
        (
            _tamper_first_action,
            ValueError,
            "Turn 1 state mismatch",
        ),
        (
            _tamper_first_post_snapshot_schema_version,
            ValueError,
            "Turn 1 snapshot schema_version mismatch",
        ),
        (
            _tamper_first_event_row,
            ValueError,
            "Turn 1 event payload mismatch",
        ),
        (
            _tamper_final_result_seat,
            ValueError,
            "Turn 7 result mismatch",
        ),
        (
            # The engine's WrongPlayer is chained as the cause (see below).
            _tamper_first_recorded_seat,
            ValueError,
            "The provided seat is not active.",
        ),
    ],
)
def test_validate_match_transcript_rejects_tampering(
    mutate,
    expected_exception,
    expected_message,
) -> None:
    payload = copy.deepcopy(dump_match_transcript(_play_connect4_win()))
    mutate(payload)

    with pytest.raises(expected_exception, match=expected_message):
        validate_match_transcript(Connect4GameDefinition, payload)


def test_load_match_transcript_rejects_invalid_and_foreign_game_ids() -> None:
    match = _build_connect4_match()
    payload = dump_match_transcript(match)

    payload["schema_version"] = 0
    with pytest.raises(ValidationError):
        load_match_transcript(Connect4GameDefinition, payload)

    payload = dump_match_transcript(match)
    payload["game_id"] = "different-game"
    with pytest.raises(ValueError, match="does not match"):
        load_match_transcript(Connect4GameDefinition, payload)


# ---------------------------------------------------------------------------
# Phase 37: turn kinds and v1 compatibility
# ---------------------------------------------------------------------------


def test_transcript_schema_bumped_for_views() -> None:
    """v2 (Phase 37): chance turns. v3 (Phase 38): a transcript declares its view,
    and a redacted one cannot be read as if it were full — a bump, not an
    additive field.
    """

    assert MATCH_TRANSCRIPT_SCHEMA_VERSION == 3


def test_action_turns_are_labelled_and_complete() -> None:
    match = start_match(Connect4GameDefinition, Connect4Config(rows=4, columns=4, connect_length=4))
    match = apply_match_action(match, 0, DropDisc(column=0))

    payload = dump_match_transcript(match)
    turn = payload["turns"][0]

    assert turn["kind"] == "action"
    assert turn["seat"] == 0
    assert turn["action"] is not None


def test_a_version_1_transcript_still_loads() -> None:
    """v1 predates chance nodes, so every one of its turns is an action turn.

    `kind` defaults and `seat`/`action` stay required in practice, so an archived
    v1 transcript keeps replaying without rewriting it.
    """

    match = start_match(Connect4GameDefinition, Connect4Config(rows=4, columns=4, connect_length=4))
    match = apply_match_action(match, 0, DropDisc(column=0))
    match = apply_match_action(match, 1, DropDisc(column=1))

    payload = dump_match_transcript(match)

    # Rewrite it as a v1 document: no schema bump, no `kind` on any turn.
    payload["schema_version"] = 1
    for turn in payload["turns"]:
        turn.pop("kind")

    loaded = load_match_transcript(Connect4GameDefinition, payload)

    assert loaded.schema_version == 1
    assert [turn.kind for turn in loaded.turns] == ["action", "action"]
    assert validate_match_transcript(Connect4GameDefinition, payload) is not None


def test_an_engine_rejection_during_replay_is_a_chained_value_error() -> None:
    payload = copy.deepcopy(dump_match_transcript(_play_connect4_win()))
    _tamper_first_recorded_seat(payload)

    with pytest.raises(ValueError) as exc:
        validate_match_transcript(Connect4GameDefinition, payload)
    assert isinstance(exc.value.__cause__, WrongPlayer)
