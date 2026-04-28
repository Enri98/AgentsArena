"""Tests for pure UI-facing payload adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pytest
from pydantic import ValidationError

from arena.adapters import TypedPayloadPolicyAdapter
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    Connect4GameDefinition,
    Connect4Observation,
    DropDisc,
)
from arena.runtime import (
    Arena,
    MatchId,
    PlayerRecord,
    dump_runtime_transcript,
    dump_session_status,
)
from arena.ui import (
    UI_ADAPTER_SCHEMA_VERSION,
    UIMatchScreenPayload,
    UIMatchStatusPayload,
    UIMatchTranscriptPayload,
    build_match_screen,
    build_match_status,
    build_match_transcript,
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


def _players() -> tuple[PlayerRecord, PlayerRecord]:
    return (
        PlayerRecord(player_id="player-1", label=None, seat=1),
        PlayerRecord(player_id="player-0", label="Red", seat=0),
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


def test_running_status_maps_to_deterministic_json_safe_screen_payload() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-running"))
    session = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            _winning_policies(),
        )
    )

    runtime_status = dump_session_status(session)
    screen_status = build_match_status(runtime_status)

    assert screen_status == build_match_status(runtime_status)
    assert json.loads(json.dumps(screen_status)) == screen_status
    assert screen_status == {
        "schema_version": UI_ADAPTER_SCHEMA_VERSION,
        "runtime_schema_version": runtime_status["schema_version"],
        "match_id": "ui-running",
        "game_id": CONNECT4_GAME_ID,
        "lifecycle": "running",
        "players": [
            {"player_id": "player-0", "seat": 0, "label": "Red"},
            {"player_id": "player-1", "seat": 1, "label": None},
        ],
        "current_seat": 0,
        "turn_count": 0,
        "result": None,
        "latest_snapshot": runtime_status["latest_snapshot"],
        "state_payload": runtime_status["latest_snapshot"]["state"],
        "abort": None,
    }
    assert "events" not in screen_status
    assert UIMatchStatusPayload.model_validate(screen_status).match_id == "ui-running"


def test_created_status_keeps_empty_runtime_state_explicit() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-created"))
    session = arena.create_session(
        Connect4GameDefinition,
        Connect4Config(),
        _players(),
        _winning_policies(),
    )

    screen_status = build_match_status(dump_session_status(session))

    assert screen_status["lifecycle"] == "created"
    assert screen_status["current_seat"] is None
    assert screen_status["turn_count"] == 0
    assert screen_status["latest_snapshot"] is None
    assert screen_status["state_payload"] is None


def test_finished_status_preserves_result_and_final_snapshot() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-finished"))
    finished = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )

    runtime_status = dump_session_status(finished)
    screen_status = build_match_status(runtime_status)

    assert screen_status["lifecycle"] == "finished"
    assert screen_status["current_seat"] is None
    assert screen_status["turn_count"] == 7
    assert screen_status["result"] == {"result_type": "Win", "payload": {"seat": 0}}
    assert screen_status["latest_snapshot"] == runtime_status["latest_snapshot"]
    assert screen_status["state_payload"] == runtime_status["latest_snapshot"]["state"]


def test_aborted_status_preserves_abort_without_synthesizing_result() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-aborted"))
    running = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            {},
        )
    )
    aborted = arena.step_session(running)

    screen_status = build_match_status(dump_session_status(aborted))

    assert screen_status["lifecycle"] == "aborted"
    assert screen_status["result"] is None
    assert screen_status["latest_snapshot"] is not None
    assert screen_status["abort"] == {
        "reason": "missing_policy",
        "message": "No policy is bound for active seat 0.",
        "cause_type": None,
        "cause_message": None,
    }


def test_transcript_mapping_separates_runtime_events_from_game_turn_events() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-transcript"))
    finished = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )
    runtime_transcript = dump_runtime_transcript(finished)

    screen_transcript = build_match_transcript(runtime_transcript)

    assert screen_transcript["schema_version"] == UI_ADAPTER_SCHEMA_VERSION
    assert screen_transcript["runtime_schema_version"] == runtime_transcript["schema_version"]
    assert all(event["event_scope"] == "runtime" for event in screen_transcript["runtime_events"])
    assert [turn["turn_index"] for turn in screen_transcript["turns"]] == list(range(1, 8))
    assert screen_transcript["turns"][-1]["result"] == {
        "result_type": "Win",
        "payload": {"seat": 0},
    }
    assert any(
        event["event_type"] == "DiscDropped"
        for turn in screen_transcript["turns"]
        for event in turn["events"]
    )
    assert UIMatchTranscriptPayload.model_validate(screen_transcript).match_id == "ui-transcript"


def test_transcript_mapping_handles_created_session_without_turn_history() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-created-transcript"))
    session = arena.create_session(
        Connect4GameDefinition,
        Connect4Config(),
        _players(),
        _winning_policies(),
    )

    screen_transcript = build_match_transcript(dump_runtime_transcript(session))

    assert screen_transcript["lifecycle"] == "created"
    assert screen_transcript["runtime_events"] == [
        {
            "event_scope": "runtime",
            "event_type": "MatchCreated",
            "payload": {
                "players": [
                    {"player_id": "player-1", "seat": 1, "label": None},
                    {"player_id": "player-0", "seat": 0, "label": "Red"},
                ]
            },
        }
    ]
    assert screen_transcript["turns"] == []


def test_transcript_mapping_rejects_unknown_runtime_schema_version() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-future-transcript"))
    session = arena.create_session(
        Connect4GameDefinition,
        Connect4Config(),
        _players(),
        _winning_policies(),
    )
    transcript = dump_runtime_transcript(session)
    transcript["schema_version"] = 2

    with pytest.raises(ValidationError):
        build_match_transcript(transcript)


def test_transcript_mapping_rejects_malformed_nested_match_transcript() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-malformed-transcript"))
    session = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )
    transcript = dump_runtime_transcript(session)
    del transcript["match_transcript"]["turns"][0]["post_snapshot"]

    with pytest.raises(ValidationError, match="post_snapshot"):
        build_match_transcript(transcript)


def test_match_screen_combines_matching_status_and_transcript_payloads() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-screen"))
    session = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )

    screen = build_match_screen(
        status_payload=dump_session_status(session),
        transcript_payload=dump_runtime_transcript(session),
    )

    assert screen["schema_version"] == UI_ADAPTER_SCHEMA_VERSION
    assert screen["status"]["match_id"] == "ui-screen"
    assert screen["transcript"]["match_id"] == "ui-screen"
    assert UIMatchScreenPayload.model_validate(screen).status.lifecycle == "finished"


def test_match_screen_rejects_mismatched_status_and_transcript_ids() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-mismatch"))
    session = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            _winning_policies(),
        )
    )
    transcript = dump_runtime_transcript(session)
    transcript["match_id"] = "other-match"

    with pytest.raises(ValueError, match="different match ids"):
        build_match_screen(
            status_payload=dump_session_status(session),
            transcript_payload=transcript,
        )


def test_match_screen_rejects_same_match_stale_lifecycle_pairing() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-stale-lifecycle"))
    running = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            _winning_policies(),
        )
    )
    finished = arena.run_session(running)

    with pytest.raises(ValueError, match="different lifecycles"):
        build_match_screen(
            status_payload=dump_session_status(running),
            transcript_payload=dump_runtime_transcript(finished),
        )


def test_match_screen_rejects_same_match_stale_turn_count_pairing() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-stale-turns"))
    running = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            _winning_policies(),
        )
    )
    one_turn = arena.step_session(running)

    with pytest.raises(ValueError, match="turn_count"):
        build_match_screen(
            status_payload=dump_session_status(running),
            transcript_payload=dump_runtime_transcript(one_turn),
        )


def test_ui_adapter_rejects_unknown_runtime_status_fields() -> None:
    arena = Arena(id_factory=lambda: MatchId("ui-extra"))
    session = arena.start_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            _winning_policies(),
        )
    )
    status = dump_session_status(session)
    status["unexpected"] = "value"

    with pytest.raises(ValidationError):
        build_match_status(status)


def test_ui_payload_models_encode_fixed_schema_versions() -> None:
    status_schema = UIMatchStatusPayload.model_json_schema()
    transcript_schema = UIMatchTranscriptPayload.model_json_schema()
    screen_schema = UIMatchScreenPayload.model_json_schema()

    assert status_schema["properties"]["schema_version"]["const"] == UI_ADAPTER_SCHEMA_VERSION
    assert transcript_schema["properties"]["schema_version"]["const"] == UI_ADAPTER_SCHEMA_VERSION
    assert screen_schema["properties"]["schema_version"]["const"] == UI_ADAPTER_SCHEMA_VERSION
