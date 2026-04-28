"""Tests for arena.cli.play.play_match driver."""

from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

from arena.adapters.in_process import TypedPayloadPolicyAdapter
from arena.cli.games.connect4 import parse_input as c4_parse
from arena.cli.play import play_match
from arena.cli.policies import HumanPolicy
from arena.games.connect4 import Connect4Config, Connect4GameDefinition, DropDisc
from arena.runtime import PlayerRecord, validate_runtime_transcript


class _ScriptedPolicy:
    def __init__(self, actions: list[Any], seat_index: int = 0) -> None:
        self._actions = list(actions)
        self._index = 0
        self._seat_index = seat_index

    def select_action(self, observation: Any) -> Any:
        if self._index >= len(self._actions):
            raise RuntimeError(
                f"Scripted seat {self._seat_index} ran out of actions after {self._index} moves."
            )
        action = self._actions[self._index]
        self._index += 1
        return action


def _players() -> tuple[PlayerRecord, PlayerRecord]:
    return (
        PlayerRecord(player_id="player-0", label="Human", seat=0),
        PlayerRecord(player_id="player-1", label="Scripted", seat=1),
    )


def _scripted_policy(actions: list[DropDisc], seat_index: int = 0) -> TypedPayloadPolicyAdapter:
    return TypedPayloadPolicyAdapter(Connect4GameDefinition, _ScriptedPolicy(actions, seat_index))


def _human_policy(lines: str) -> TypedPayloadPolicyAdapter:
    stdin = io.StringIO(lines)
    stdout = io.StringIO()
    policy = HumanPolicy(c4_parse, stdin=stdin, stdout=stdout)
    return TypedPayloadPolicyAdapter(Connect4GameDefinition, policy)


def test_full_game_returns_zero_and_writes_files(tmp_path: Path) -> None:
    cfg = Connect4Config(rows=4, columns=4, connect_length=4)
    policies = {
        0: _human_policy("0\n0\n0\n0\n"),
        1: _scripted_policy([DropDisc(column=1), DropDisc(column=1), DropDisc(column=1)]),
    }
    out = io.StringIO()
    code = play_match(
        Connect4GameDefinition,
        cfg,
        _players(),
        policies,
        out_dir=tmp_path,
        stdout=out,
    )
    assert code == 0
    rendered = out.getvalue()
    assert "finished" in rendered

    status_path = tmp_path / "status.json"
    transcript_path = tmp_path / "transcript.json"
    assert status_path.exists()
    assert transcript_path.exists()

    transcript_payload = json.loads(transcript_path.read_text(encoding="utf-8"))
    validate_runtime_transcript(Connect4GameDefinition, transcript_payload)


def test_mid_game_quit_returns_nonzero(tmp_path: Path) -> None:
    cfg = Connect4Config(rows=4, columns=4, connect_length=4)
    policies = {
        0: _human_policy("0\nq\n"),
        1: _scripted_policy([DropDisc(column=1), DropDisc(column=1), DropDisc(column=1)]),
    }
    out = io.StringIO()
    code = play_match(
        Connect4GameDefinition,
        cfg,
        _players(),
        policies,
        out_dir=tmp_path,
        stdout=out,
    )
    assert code != 0
    rendered = out.getvalue()
    assert "aborted" in rendered.lower() or "Aborted" in rendered

    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["lifecycle"] == "aborted"
    assert status["abort"]["reason"] == "user_quit"


def test_mid_game_eof_returns_nonzero(tmp_path: Path) -> None:
    cfg = Connect4Config(rows=4, columns=4, connect_length=4)
    policies = {
        0: _human_policy("0\n"),
        1: _scripted_policy([DropDisc(column=1), DropDisc(column=1), DropDisc(column=1)]),
    }
    out = io.StringIO()
    code = play_match(
        Connect4GameDefinition,
        cfg,
        _players(),
        policies,
        out_dir=tmp_path,
        stdout=out,
    )
    assert code != 0
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["lifecycle"] == "aborted"
    assert status["abort"]["reason"] == "user_quit"


def test_keyboard_interrupt_returns_nonzero(tmp_path: Path) -> None:
    class _InterruptingStdin:
        def readline(self) -> str:
            raise KeyboardInterrupt

    stdout_io = io.StringIO()
    policy = HumanPolicy(c4_parse, stdin=_InterruptingStdin(), stdout=stdout_io)
    wrapped = TypedPayloadPolicyAdapter(Connect4GameDefinition, policy)

    cfg = Connect4Config(rows=4, columns=4, connect_length=4)
    policies = {
        0: wrapped,
        1: _scripted_policy([DropDisc(column=1), DropDisc(column=1), DropDisc(column=1)]),
    }
    out = io.StringIO()
    code = play_match(
        Connect4GameDefinition,
        cfg,
        _players(),
        policies,
        out_dir=tmp_path,
        stdout=out,
    )
    assert code != 0
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["lifecycle"] == "aborted"
    assert status["abort"]["reason"] == "user_interrupt"


def test_quit_mid_turn_transcript_has_turn_requested_before_match_aborted(
    tmp_path: Path,
) -> None:
    cfg = Connect4Config(rows=4, columns=4, connect_length=4)
    policies = {
        0: _human_policy("q\n"),
        1: _scripted_policy([DropDisc(column=1), DropDisc(column=1), DropDisc(column=1)]),
    }
    out = io.StringIO()
    code = play_match(
        Connect4GameDefinition,
        cfg,
        _players(),
        policies,
        out_dir=tmp_path,
        stdout=out,
    )
    assert code != 0

    transcript = json.loads((tmp_path / "transcript.json").read_text(encoding="utf-8"))
    event_types = [e["event_type"] for e in transcript["events"]]

    assert "TurnRequested" in event_types
    assert "MatchAborted" in event_types
    turn_idx = event_types.index("TurnRequested")
    abort_idx = event_types.index("MatchAborted")
    assert turn_idx < abort_idx

    abort_event = transcript["events"][abort_idx]
    assert abort_event["payload"]["abort"]["reason"] == "user_quit"


def test_scripted_policy_exhaustion_abort_has_informative_cause_message(
    tmp_path: Path,
) -> None:
    cfg = Connect4Config(rows=4, columns=4, connect_length=4)
    policies = {
        0: _scripted_policy([DropDisc(column=0)], seat_index=0),
        1: _scripted_policy([], seat_index=1),
    }
    out = io.StringIO()
    code = play_match(
        Connect4GameDefinition,
        cfg,
        _players(),
        policies,
        out_dir=tmp_path,
        stdout=out,
    )
    assert code != 0

    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["lifecycle"] == "aborted"
    assert status["abort"]["reason"] == "adapter_error"
    cause_message = status["abort"].get("cause_message", "")
    assert cause_message is not None
    assert "ran out of actions" in cause_message
