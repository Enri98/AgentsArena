"""Tests for the transcript file loader and frame entrypoint (Slice 4)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from arena.adapters import TypedPayloadPolicyAdapter
from arena.cli.app import render_all_frames, render_session_from_files
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
)


@dataclass
class ScriptedAgent:
    actions: tuple[DropDisc, ...]
    index: int = 0

    def select_action(self, observation: Connect4Observation) -> DropDisc:
        action = self.actions[self.index]
        self.index += 1
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


def _dump_session(tmp_path: Path) -> tuple[Path, Path]:
    """Run a scripted session and dump status + transcript JSON files."""
    arena = Arena(id_factory=lambda: MatchId("app-test"))
    session = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )

    status_path = tmp_path / "status.json"
    transcript_path = tmp_path / "transcript.json"
    status_path.write_text(
        json.dumps(dump_session_status(session)), encoding="utf-8"
    )
    transcript_path.write_text(
        json.dumps(dump_runtime_transcript(session)), encoding="utf-8"
    )
    return status_path, transcript_path


def test_render_latest_frame_is_deterministic(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    result_a = render_session_from_files(status_path, transcript_path)
    result_b = render_session_from_files(status_path, transcript_path)

    assert result_a == result_b
    assert isinstance(result_a, str)
    assert len(result_a) > 0


def test_render_frame_0(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    result = render_session_from_files(status_path, transcript_path, turn=0)

    assert isinstance(result, str)
    assert len(result) > 0
    assert "Turn history:" in result
    assert "#1 seat=0" in result
    assert "#2" not in result


def test_render_mid_game_frame(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    result = render_session_from_files(status_path, transcript_path, turn=3)

    assert isinstance(result, str)
    assert "#4" in result
    assert "#5" not in result


def test_render_terminal_frame(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    transcript_data = json.loads(transcript_path.read_text(encoding="utf-8"))
    n_turns = len(
        transcript_data.get("match_transcript", {}).get("turns", [])
    )
    last_turn = n_turns - 1

    result = render_session_from_files(status_path, transcript_path, turn=last_turn)

    assert isinstance(result, str)
    assert len(result) > 0


def test_render_frame_deterministic_across_calls(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    a = render_session_from_files(status_path, transcript_path, turn=2)
    b = render_session_from_files(status_path, transcript_path, turn=2)

    assert a == b


def test_render_all_frames_includes_separators(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    result = render_all_frames(status_path, transcript_path)

    assert "=== Turn 0 ===" in result
    assert isinstance(result, str)
    assert len(result) > 0


def test_render_all_frames_includes_all_turn_separators(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    transcript_data = json.loads(transcript_path.read_text(encoding="utf-8"))
    n_turns = len(transcript_data.get("match_transcript", {}).get("turns", []))

    result = render_all_frames(status_path, transcript_path)

    for idx in range(n_turns):
        assert f"=== Turn {idx} ===" in result


def test_render_all_frames_is_deterministic(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    a = render_all_frames(status_path, transcript_path)
    b = render_all_frames(status_path, transcript_path)

    assert a == b


def test_out_of_range_turn_raises_index_error(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    with pytest.raises(IndexError, match="999"):
        render_session_from_files(status_path, transcript_path, turn=999)


def test_corrupted_status_json_raises(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    status_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(Exception):
        render_session_from_files(status_path, transcript_path)


def test_schema_version_mismatch_raises(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    status_data = json.loads(status_path.read_text(encoding="utf-8"))
    status_data["schema_version"] = 99
    status_path.write_text(json.dumps(status_data), encoding="utf-8")

    with pytest.raises(Exception):
        render_session_from_files(status_path, transcript_path)


def test_corrupted_transcript_json_raises(tmp_path: Path) -> None:
    status_path, transcript_path = _dump_session(tmp_path)

    transcript_path.write_text("{bad json", encoding="utf-8")

    with pytest.raises(Exception):
        render_session_from_files(status_path, transcript_path)
