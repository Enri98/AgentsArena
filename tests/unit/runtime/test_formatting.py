"""Tests for deterministic human-readable runtime formatting helpers."""

from __future__ import annotations

import copy
from dataclasses import dataclass

import pytest
from pydantic import ValidationError

from arena.adapters import TypedPayloadPolicyAdapter
from arena.games.connect4 import (
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
    format_runtime_session_report,
    format_runtime_transcript,
    format_session_status,
)


@dataclass
class ScriptedAgent:
    actions: tuple[DropDisc, ...]
    index: int = 0

    def select_action(self, observation: Connect4Observation) -> DropDisc:
        action = self.actions[self.index]
        self.index += 1
        assert action in observation.legal_actions
        return action


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


def test_format_completed_runtime_session_report_from_payloads() -> None:
    arena = Arena(id_factory=lambda: MatchId("completed-demo"))
    session = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )

    report = format_runtime_session_report(
        status_payload=dump_session_status(session),
        transcript_payload=dump_runtime_transcript(session),
    )

    assert report.startswith(
        "\n".join(
            (
                "Runtime session status",
                "Match: completed-demo",
                "Game: connect4",
                "Lifecycle: finished",
                "Players:",
                "- seat 0: Red (player-0)",
                "- seat 1: Yellow (player-1)",
                "Turn count: 7",
                "Current turn: none",
                'Result: Win {"seat": 0}',
            )
        )
    )
    assert "Runtime events:" in report
    assert "- MatchCreated:" in report
    assert "- MatchFinished: {}" in report
    assert "Turn history:" in report
    assert '- turn 1: seat 0 action={"column": 0}' in report
    assert (
        'game events: DiscDropped {"column": 0, "row": 3, "seat": 0}'
        in report
    )
    assert '- turn 7: seat 0 action={"column": 0}' in report
    assert (
        'game events: DiscDropped {"column": 0, "row": 0, "seat": 0}, '
        'WinnerDetected {"winning_seat": 0}'
        in report
    )
    assert '  result: Win {"seat": 0}' in report
    assert "event_scope" not in report


def test_format_aborted_runtime_session_status_and_transcript_from_payloads() -> None:
    arena = Arena(id_factory=lambda: MatchId("aborted-demo"))
    session = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(),
            _players(),
            {},
        )
    )

    status_text = format_session_status(dump_session_status(session))
    transcript_text = format_runtime_transcript(dump_runtime_transcript(session))

    assert status_text == "\n".join(
        (
            "Runtime session status",
            "Match: aborted-demo",
            "Game: connect4",
            "Lifecycle: aborted",
            "Players:",
            "- seat 0: Red (player-0)",
            "- seat 1: Yellow (player-1)",
            "Turn count: 0",
            "Current turn: seat 0",
            "Result: ongoing",
            "Abort:",
            "- reason: missing_policy",
            "- message: No policy is bound for active seat 0.",
            "- cause: none",
            "Latest snapshot: schema_version=1, game_id=connect4",
        )
    )
    assert "Lifecycle: aborted" in transcript_text
    assert "Abort:" in transcript_text
    assert "- MatchAborted:" in transcript_text
    assert "Turn history:\n- none" in transcript_text
    assert "DiscDropped" not in transcript_text


def test_runtime_session_report_rejects_mismatched_payloads() -> None:
    arena = Arena(id_factory=lambda: MatchId("first-demo"))
    first_session = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )
    second_arena = Arena(id_factory=lambda: MatchId("second-demo"))
    second_session = second_arena.run_session(
        second_arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )

    with pytest.raises(ValueError, match="different match ids"):
        format_runtime_session_report(
            status_payload=dump_session_status(first_session),
            transcript_payload=dump_runtime_transcript(second_session),
        )


def test_runtime_transcript_formatting_validates_nested_match_transcript_shape() -> None:
    arena = Arena(id_factory=lambda: MatchId("malformed-demo"))
    session = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )
    payload = copy.deepcopy(dump_runtime_transcript(session))
    del payload["match_transcript"]["turns"]

    with pytest.raises(ValidationError, match="turns"):
        format_runtime_transcript(payload)
