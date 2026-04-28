"""Tests for pure runtime arena session coordination."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from pydantic import ValidationError

from arena.adapters import (
    ActionResponsePayload,
    ObservationRequestPayload,
    TypedPayloadPolicyAdapter,
)
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    Connect4GameDefinition,
    Connect4Observation,
    DropDisc,
)
from arena.runtime import (
    RUNTIME_STATUS_SCHEMA_VERSION,
    AbortReason,
    Arena,
    MatchId,
    PlayerRecord,
    RuntimeLifecycle,
    RuntimeSessionStatusPayload,
    RuntimeStateError,
    RuntimeTranscriptPayload,
    dump_runtime_transcript,
    dump_session_status,
    validate_runtime_transcript,
    validate_session_status,
)


@dataclass
class ScriptedAgent:
    actions: tuple[DropDisc, ...]
    observations: list[Connect4Observation] = field(default_factory=list)
    index: int = 0

    def select_action(self, observation: Connect4Observation) -> DropDisc:
        self.observations.append(observation)
        action = self.actions[self.index]
        self.index += 1
        return action


@dataclass
class RaisingPayloadPolicy:
    error: Exception

    def select_action(self, request: ObservationRequestPayload) -> ActionResponsePayload:
        raise self.error


def _players() -> tuple[PlayerRecord, PlayerRecord]:
    return (
        PlayerRecord(player_id="player-0", label="Red", seat=0),
        PlayerRecord(player_id="player-1", label="Yellow", seat=1),
    )


def _winning_policies() -> dict[int, TypedPayloadPolicyAdapter]:
    return {
        0: TypedPayloadPolicyAdapter(
            Connect4GameDefinition,
            ScriptedAgent(
                actions=(
                    DropDisc(column=0),
                    DropDisc(column=0),
                    DropDisc(column=0),
                    DropDisc(column=0),
                )
            ),
        ),
        1: TypedPayloadPolicyAdapter(
            Connect4GameDefinition,
            ScriptedAgent(
                actions=(
                    DropDisc(column=1),
                    DropDisc(column=1),
                    DropDisc(column=1),
                )
            ),
        ),
    }


def test_arena_creates_started_and_finished_local_session() -> None:
    arena = Arena(id_factory=lambda: MatchId("fixed-match"))
    session = arena.create_session(
        Connect4GameDefinition,
        Connect4Config(rows=4, columns=4, connect_length=4),
        _players(),
        _winning_policies(),
    )

    assert session.match_id == "fixed-match"
    assert session.lifecycle is RuntimeLifecycle.CREATED
    assert session.local_match is None
    assert session.events[0].event_type == "MatchCreated"

    running = arena.start_session(session)

    assert running.lifecycle is RuntimeLifecycle.RUNNING
    assert running.local_match is not None
    assert running.events[-1].event_type == "MatchStarted"

    finished = arena.run_session(running)

    assert finished.lifecycle is RuntimeLifecycle.FINISHED
    assert finished.local_match is not None
    assert len(finished.local_match.turns) == 7
    assert finished.events[-1].event_type == "MatchFinished"


def test_step_session_records_turn_runtime_events() -> None:
    arena = Arena(id_factory=lambda: MatchId("step-match"))
    session = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            _winning_policies(),
        )
    )

    next_session = arena.step_session(session)

    assert next_session.lifecycle is RuntimeLifecycle.RUNNING
    assert [event.event_type for event in next_session.events[-2:]] == [
        "TurnRequested",
        "TurnAccepted",
    ]
    assert next_session.local_match is not None
    assert next_session.local_match.turns[-1].seat == 0


def test_missing_policy_aborts_without_game_result() -> None:
    arena = Arena(id_factory=lambda: MatchId("missing-policy"))
    session = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            {},
        )
    )

    aborted = arena.step_session(session)

    assert aborted.lifecycle is RuntimeLifecycle.ABORTED
    assert aborted.abort is not None
    assert aborted.abort.reason is AbortReason.MISSING_POLICY
    assert aborted.events[-1].event_type == "MatchAborted"


def test_illegal_policy_action_aborts_and_preserves_core_cause() -> None:
    arena = Arena(id_factory=lambda: MatchId("illegal-action"))
    session = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            {
                0: TypedPayloadPolicyAdapter(
                    Connect4GameDefinition,
                    ScriptedAgent(actions=(DropDisc(column=99),)),
                )
            },
        )
    )

    aborted = arena.step_session(session)

    assert aborted.lifecycle is RuntimeLifecycle.ABORTED
    assert aborted.abort is not None
    assert aborted.abort.reason is AbortReason.CORE_ERROR
    assert aborted.abort.cause_type == "IllegalAction"


def test_policy_exception_aborts_as_adapter_error() -> None:
    arena = Arena(id_factory=lambda: MatchId("adapter-error"))
    session = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            {0: RaisingPayloadPolicy(RuntimeError("boom"))},
        )
    )

    aborted = arena.step_session(session)

    assert aborted.lifecycle is RuntimeLifecycle.ABORTED
    assert aborted.abort is not None
    assert aborted.abort.reason is AbortReason.ADAPTER_ERROR
    assert aborted.abort.cause_type == "RuntimeError"
    assert aborted.abort.cause_message == "boom"


def test_runtime_rejects_invalid_lifecycle_transitions() -> None:
    arena = Arena(id_factory=lambda: MatchId("invalid-transition"))
    session = arena.create_session(
        Connect4GameDefinition,
        Connect4Config(),
        _players(),
        _winning_policies(),
    )

    with pytest.raises(RuntimeStateError, match="Only running"):
        arena.step_session(session)

    running = arena.start_session(session)

    with pytest.raises(RuntimeStateError, match="Only created"):
        arena.start_session(running)


def test_status_payload_is_ui_ready_without_rendering_assumptions() -> None:
    arena = Arena(id_factory=lambda: MatchId("status-match"))
    session = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            _winning_policies(),
        )
    )

    payload = dump_session_status(session)

    assert payload == {
        "schema_version": RUNTIME_STATUS_SCHEMA_VERSION,
        "match_id": "status-match",
        "game_id": CONNECT4_GAME_ID,
        "lifecycle": "running",
        "players": [
        {"player_id": "player-0", "seat": 0, "label": "Red"},
        {"player_id": "player-1", "seat": 1, "label": "Yellow"},
        ],
        "current_seat": 0,
        "turn_count": 0,
        "result": None,
        "latest_snapshot": session.local_match.initial_snapshot.model_dump(mode="json"),
        "abort": None,
    }
    validated = validate_session_status(payload)
    assert validated.schema_version == RUNTIME_STATUS_SCHEMA_VERSION


def test_finished_status_payload_is_stable_and_rendering_agnostic() -> None:
    arena = Arena(id_factory=lambda: MatchId("finished-status"))
    finished = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )

    assert finished.local_match is not None
    payload = dump_session_status(finished)
    last_snapshot = finished.local_match.turns[-1].post_snapshot.model_dump(mode="json")

    assert payload == {
        "schema_version": RUNTIME_STATUS_SCHEMA_VERSION,
        "match_id": "finished-status",
        "game_id": CONNECT4_GAME_ID,
        "lifecycle": "finished",
        "players": [
            {"player_id": "player-0", "seat": 0, "label": "Red"},
            {"player_id": "player-1", "seat": 1, "label": "Yellow"},
        ],
        "current_seat": None,
        "turn_count": 7,
        "result": {"result_type": "Win", "payload": {"seat": 0}},
        "latest_snapshot": last_snapshot,
        "abort": None,
    }
    validated = validate_session_status(payload)
    assert validated.lifecycle == "finished"


def test_aborted_status_payload_is_stable_without_runtime_event_list() -> None:
    arena = Arena(id_factory=lambda: MatchId("aborted-status"))
    running = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            {},
        )
    )

    assert running.local_match is not None
    aborted = arena.step_session(running)
    payload = dump_session_status(aborted)

    assert payload == {
        "schema_version": RUNTIME_STATUS_SCHEMA_VERSION,
        "match_id": "aborted-status",
        "game_id": CONNECT4_GAME_ID,
        "lifecycle": "aborted",
        "players": [
            {"player_id": "player-0", "seat": 0, "label": "Red"},
            {"player_id": "player-1", "seat": 1, "label": "Yellow"},
        ],
        "current_seat": 0,
        "turn_count": 0,
        "result": None,
        "latest_snapshot": running.local_match.initial_snapshot.model_dump(mode="json"),
        "abort": {
            "reason": "missing_policy",
            "message": "No policy is bound for active seat 0.",
            "cause_type": None,
            "cause_message": None,
        },
    }
    assert "events" not in payload
    validated = validate_session_status(payload)
    assert validated.lifecycle == "aborted"


def test_runtime_transcript_wraps_match_transcript_and_validates_explicitly() -> None:
    arena = Arena(id_factory=lambda: MatchId("transcript-match"))
    finished = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )

    payload = dump_runtime_transcript(finished)
    loaded = validate_runtime_transcript(Connect4GameDefinition, payload)

    assert payload["match_id"] == "transcript-match"
    assert payload["lifecycle"] == "finished"
    assert all(event["event_scope"] == "runtime" for event in payload["events"])
    assert payload["match_transcript"]["game_id"] == CONNECT4_GAME_ID
    assert loaded is not None
    assert loaded.latest_state == finished.local_match.state


def test_session_status_validation_rejects_unknown_schema_version() -> None:
    arena = Arena(id_factory=lambda: MatchId("future-status"))
    session = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            _winning_policies(),
        )
    )
    payload = dump_session_status(session)
    payload["schema_version"] = 2

    with pytest.raises(ValueError, match="schema_version"):
        validate_session_status(payload)


def test_runtime_payload_models_encode_fixed_schema_versions() -> None:
    status_schema = RuntimeSessionStatusPayload.model_json_schema()
    transcript_schema = RuntimeTranscriptPayload.model_json_schema()

    assert status_schema["properties"]["schema_version"]["const"] == 1
    assert transcript_schema["properties"]["schema_version"]["const"] == 1


def test_runtime_transcript_validation_rejects_missing_runtime_event_scope() -> None:
    arena = Arena(id_factory=lambda: MatchId("missing-event-scope"))
    finished = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )
    payload = dump_runtime_transcript(finished)
    del payload["events"][0]["event_scope"]

    with pytest.raises(ValidationError, match="event_scope"):
        validate_runtime_transcript(Connect4GameDefinition, payload)


def test_runtime_transcript_validation_rejects_unknown_schema_version() -> None:
    arena = Arena(id_factory=lambda: MatchId("future-transcript"))
    finished = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )
    payload = dump_runtime_transcript(finished)
    payload["schema_version"] = 2

    with pytest.raises(ValueError, match="schema_version"):
        validate_runtime_transcript(Connect4GameDefinition, payload)
