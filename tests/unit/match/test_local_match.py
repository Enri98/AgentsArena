"""Tests for pure local match execution."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from arena.core.exceptions import GameFinished, IllegalAction
from arena.core.registry import GameRegistry
from arena.core.results import RuleResult, Win
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    Connect4GameDefinition,
    Connect4Observation,
    Connect4State,
    DiscDropped,
    DropDisc,
    WinnerDetected,
    register_connect4,
)
from arena.match import (
    LocalMatch,
    apply_match_action,
    apply_policy_turn,
    run_local_match,
    start_match,
)


def _build_connect4_match() -> LocalMatch[
    Connect4Config,
    Connect4State,
    DropDisc,
    Connect4Observation,
    RuleResult,
]:
    registry = GameRegistry()
    register_connect4(registry)
    definition = registry.get(CONNECT4_GAME_ID)
    config = Connect4Config(rows=4, columns=4, connect_length=4)
    return start_match(definition, config)


@dataclass
class RecordingPolicy:
    action: DropDisc
    observations: list[Connect4Observation] = field(default_factory=list)

    def select_action(self, observation: Connect4Observation) -> DropDisc:
        self.observations.append(observation)
        return self.action


@dataclass
class ScriptedPolicy:
    actions: tuple[DropDisc, ...]
    observations: list[Connect4Observation] = field(default_factory=list)
    index: int = 0

    def select_action(self, observation: Connect4Observation) -> DropDisc:
        self.observations.append(observation)
        action = self.actions[self.index]
        self.index += 1
        return action


def test_start_match_records_initial_state_and_snapshot() -> None:
    match = _build_connect4_match()

    assert match.definition is Connect4GameDefinition
    assert match.rules_engine is not match.definition.rules_engine
    assert match.state == match.rules_engine.initial_state(match.config)
    assert match.turns == ()
    assert match.initial_snapshot.game_id == CONNECT4_GAME_ID
    assert match.initial_snapshot.schema_version == 1
    assert match.initial_snapshot.config == {"rows": 4, "columns": 4, "connect_length": 4}
    assert match.initial_snapshot.state == {
        "board": [
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ],
        "current_seat": 0,
    }


def test_apply_policy_turn_passes_observation_to_active_policy_and_appends_one_turn() -> None:
    match = _build_connect4_match()
    policy = RecordingPolicy(action=DropDisc(column=0))

    next_match = apply_policy_turn(match, {0: policy})

    assert len(policy.observations) == 1
    assert policy.observations[0] == match.rules_engine.observation(match.state, 0)
    assert len(next_match.turns) == 1
    assert next_match.turns[0].seat == 0
    assert next_match.turns[0].action == DropDisc(column=0)


def test_apply_match_action_appends_a_turn_and_keeps_previous_match_immutable() -> None:
    match = _build_connect4_match()
    next_match = apply_match_action(match, 0, DropDisc(column=0))

    assert next_match is not match
    assert match.turns == ()
    assert len(next_match.turns) == 1
    assert next_match.state != match.state
    assert next_match.turns[0].seat == 0
    assert next_match.turns[0].action == DropDisc(column=0)
    assert next_match.turns[0].events == (DiscDropped(seat=0, column=0, row=3),)
    assert next_match.turns[0].result is None
    assert next_match.turns[0].post_state == next_match.state
    assert next_match.turns[0].post_snapshot.state == {
        "board": [
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [1, 0, 0, 0],
        ],
        "current_seat": 1,
    }


def test_connect4_local_match_captures_a_terminal_win_sequence() -> None:
    match = _build_connect4_match()
    moves = [0, 1, 0, 1, 0, 1, 0]

    for column in moves[:-1]:
        match = apply_match_action(
            match,
            match.rules_engine.current_seat(match.state),
            DropDisc(column=column),
        )

    final_match = apply_match_action(
        match,
        match.rules_engine.current_seat(match.state),
        DropDisc(column=moves[-1]),
    )

    final_turn = final_match.turns[-1]

    assert final_match.rules_engine.result(final_match.state) == Win(seat=0)
    assert final_turn.result == Win(seat=0)
    assert final_turn.events == (
        DiscDropped(seat=0, column=0, row=0),
        WinnerDetected(winning_seat=0),
    )
    assert final_turn.post_snapshot.state["current_seat"] == 0
    assert isinstance(final_turn.post_snapshot.state, dict)


def test_run_local_match_completes_connect4_with_two_deterministic_policies() -> None:
    match = _build_connect4_match()
    seat0_policy = ScriptedPolicy(
        actions=(DropDisc(column=0), DropDisc(column=0), DropDisc(column=0), DropDisc(column=0))
    )
    seat1_policy = ScriptedPolicy(
        actions=(DropDisc(column=1), DropDisc(column=1), DropDisc(column=1))
    )

    final_match = run_local_match(match, {0: seat0_policy, 1: seat1_policy})

    assert final_match.rules_engine.is_terminal(final_match.state)
    assert final_match.rules_engine.result(final_match.state) == Win(seat=0)
    assert [turn.seat for turn in final_match.turns] == [0, 1, 0, 1, 0, 1, 0]
    assert [turn.action for turn in final_match.turns] == [
        DropDisc(column=0),
        DropDisc(column=1),
        DropDisc(column=0),
        DropDisc(column=1),
        DropDisc(column=0),
        DropDisc(column=1),
        DropDisc(column=0),
    ]


def test_local_match_surfaces_illegal_and_post_terminal_domain_exceptions() -> None:
    match = _build_connect4_match()

    with pytest.raises(IllegalAction):
        apply_match_action(match, 0, DropDisc(column=4))

    with pytest.raises(IllegalAction):
        apply_policy_turn(match, {0: RecordingPolicy(action=DropDisc(column=4))})

    winning_match = match
    for column in (0, 1, 0, 1, 0, 1, 0):
        winning_match = apply_match_action(
            winning_match,
            winning_match.rules_engine.current_seat(winning_match.state),
            DropDisc(column=column),
        )

    with pytest.raises(GameFinished):
        apply_match_action(
            winning_match,
            winning_match.rules_engine.current_seat(winning_match.state),
            DropDisc(column=2),
        )


def test_missing_active_seat_policy_fails_clearly() -> None:
    match = _build_connect4_match()

    with pytest.raises(KeyError, match="0"):
        apply_policy_turn(match, {1: RecordingPolicy(action=DropDisc(column=0))})


def test_local_matches_use_isolated_rules_engines_per_configuration() -> None:
    short_match = start_match(Connect4GameDefinition, Connect4Config(connect_length=3))

    short_match = apply_match_action(
        short_match,
        short_match.rules_engine.current_seat(short_match.state),
        DropDisc(column=0),
    )

    default_match = start_match(Connect4GameDefinition, Connect4Config())

    for column in (1, 0, 1, 0):
        short_match = apply_match_action(
            short_match,
            short_match.rules_engine.current_seat(short_match.state),
            DropDisc(column=column),
        )

    assert short_match.rules_engine.result(short_match.state) == Win(seat=0)
    assert short_match.turns[-1].result == Win(seat=0)
    assert default_match.rules_engine.result(default_match.state) is None
