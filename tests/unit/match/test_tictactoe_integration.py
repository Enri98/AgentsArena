"""Cross-layer integration tests for Tic-Tac-Toe."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from arena.core.results import Win
from arena.games import build_default_registry
from arena.games.tictactoe import (
    TICTACTOE_GAME_ID,
    PlaceMark,
    TicTacToeConfig,
    TicTacToeGameDefinition,
    TicTacToeObservation,
)
from arena.match import (
    apply_match_action,
    dump_match_transcript,
    run_local_match,
    start_match,
    validate_match_transcript,
)


def test_build_default_registry_resolves_tictactoe() -> None:
    registry = build_default_registry()

    assert registry.get(TICTACTOE_GAME_ID) is TicTacToeGameDefinition


def test_start_match_and_apply_match_action_work_for_tictactoe() -> None:
    registry = build_default_registry()
    definition = registry.get(TICTACTOE_GAME_ID)
    match = start_match(definition, TicTacToeConfig())

    next_match = apply_match_action(match, 0, PlaceMark(row=0, column=0))

    assert next_match is not match
    assert next_match.turns[0].seat == 0
    assert next_match.turns[0].action == PlaceMark(row=0, column=0)
    assert next_match.turns[0].post_state.current_seat == 1
    assert next_match.turns[0].post_snapshot.game_id == TICTACTOE_GAME_ID
    assert next_match.turns[0].post_snapshot.state["board"][0][0] == 1


def test_dump_and_validate_match_transcript_work_for_a_completed_tictactoe_match() -> None:
    registry = build_default_registry()
    definition = registry.get(TICTACTOE_GAME_ID)
    match = start_match(definition, TicTacToeConfig())

    for seat, action in (
        (0, PlaceMark(row=0, column=0)),
        (1, PlaceMark(row=1, column=0)),
        (0, PlaceMark(row=0, column=1)),
        (1, PlaceMark(row=1, column=1)),
        (0, PlaceMark(row=0, column=2)),
    ):
        match = apply_match_action(match, seat, action)

    payload = dump_match_transcript(match)
    loaded = validate_match_transcript(definition, payload)

    assert json.dumps(payload)
    assert payload["game_id"] == TICTACTOE_GAME_ID
    assert loaded.definition is definition
    assert loaded.latest_state == match.state
    assert loaded.turns[-1].result == Win(seat=0)


@dataclass
class ScriptedPolicy:
    actions: tuple[PlaceMark, ...]
    observations: list[TicTacToeObservation] = field(default_factory=list)
    index: int = 0

    def select_action(self, observation: TicTacToeObservation) -> PlaceMark:
        self.observations.append(observation)
        action = self.actions[self.index]
        self.index += 1
        return action


def test_run_local_match_works_with_deterministic_tictactoe_policies() -> None:
    registry = build_default_registry()
    definition = registry.get(TICTACTOE_GAME_ID)
    match = start_match(definition, TicTacToeConfig())
    seat0_policy = ScriptedPolicy(
        actions=(
            PlaceMark(row=0, column=0),
            PlaceMark(row=0, column=1),
            PlaceMark(row=0, column=2),
        )
    )
    seat1_policy = ScriptedPolicy(
        actions=(
            PlaceMark(row=1, column=0),
            PlaceMark(row=1, column=1),
        )
    )

    final_match = run_local_match(match, {0: seat0_policy, 1: seat1_policy})

    assert final_match.rules_engine.is_terminal(final_match.state)
    assert final_match.rules_engine.result(final_match.state) == Win(seat=0)
    assert [turn.action for turn in final_match.turns] == [
        PlaceMark(row=0, column=0),
        PlaceMark(row=1, column=0),
        PlaceMark(row=0, column=1),
        PlaceMark(row=1, column=1),
        PlaceMark(row=0, column=2),
    ]
