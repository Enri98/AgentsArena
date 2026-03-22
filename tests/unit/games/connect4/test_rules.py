"""Tests for the Connect 4 rules-engine scaffold."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from arena.core.actions import Action
from arena.core.exceptions import GameFinished, IllegalAction, WrongPlayer
from arena.core.results import Draw, Win
from arena.games.connect4 import (
    Connect4Config,
    Connect4Observation,
    Connect4RulesEngine,
    Connect4State,
    DiscDropped,
    DropDisc,
    EMPTY_CELL,
    GameDrawn,
    SEAT0_DISC,
    SEAT1_DISC,
    WinnerDetected,
    __all__ as connect4_exports,
)


@dataclass(frozen=True)
class FakeAction(Action):
    """Non-Connect-4 action used for validation tests."""


def test_initial_state_builds_an_empty_immutable_board_from_config() -> None:
    rules = Connect4RulesEngine()
    config = Connect4Config(rows=4, columns=5, connect_length=4)

    state = rules.initial_state(config)

    assert state == Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )


def test_current_seat_returns_the_state_seat_without_hidden_context() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=((EMPTY_CELL, EMPTY_CELL), (SEAT0_DISC, EMPTY_CELL)),
        current_seat=1,
    )

    assert rules.current_seat(state) == 1


def test_legal_actions_return_left_to_right_playable_columns() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=(
            (SEAT0_DISC, EMPTY_CELL, SEAT1_DISC, EMPTY_CELL),
            (SEAT1_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    assert rules.legal_actions(state, 0) == (
        DropDisc(column=1),
        DropDisc(column=3),
    )


def test_legal_actions_return_empty_for_wrong_seat() -> None:
    rules = Connect4RulesEngine()
    state = rules.initial_state(Connect4Config())

    assert rules.legal_actions(state, 1) == ()


def test_legal_actions_return_empty_for_terminal_states() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=(
            (SEAT0_DISC, SEAT0_DISC, SEAT1_DISC, SEAT1_DISC),
            (SEAT1_DISC, SEAT1_DISC, SEAT0_DISC, SEAT0_DISC),
            (SEAT0_DISC, SEAT0_DISC, SEAT1_DISC, SEAT1_DISC),
            (SEAT1_DISC, SEAT1_DISC, SEAT0_DISC, SEAT0_DISC),
        ),
        current_seat=0,
    )

    assert rules.is_terminal(state) is True
    assert rules.result(state) == Draw()
    assert rules.legal_actions(state, 0) == ()


def test_validate_action_rejects_moves_after_game_finished() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=(
            (SEAT0_DISC, SEAT0_DISC, SEAT1_DISC, SEAT1_DISC),
            (SEAT1_DISC, SEAT1_DISC, SEAT0_DISC, SEAT0_DISC),
            (SEAT0_DISC, SEAT0_DISC, SEAT1_DISC, SEAT1_DISC),
            (SEAT1_DISC, SEAT1_DISC, SEAT0_DISC, SEAT0_DISC),
        ),
        current_seat=0,
    )

    with pytest.raises(GameFinished):
        rules.validate_action(state, 0, DropDisc(column=0))


def test_validate_action_rejects_wrong_player() -> None:
    rules = Connect4RulesEngine()
    state = rules.initial_state(Connect4Config())

    with pytest.raises(WrongPlayer):
        rules.validate_action(state, 1, DropDisc(column=0))


def test_validate_action_rejects_wrong_action_type() -> None:
    rules = Connect4RulesEngine()
    state = rules.initial_state(Connect4Config())

    with pytest.raises(IllegalAction):
        rules.validate_action(state, 0, FakeAction())


def test_validate_action_rejects_out_of_bounds_columns() -> None:
    rules = Connect4RulesEngine()
    state = rules.initial_state(Connect4Config(rows=4, columns=4, connect_length=4))

    with pytest.raises(IllegalAction):
        rules.validate_action(state, 0, DropDisc(column=4))


def test_validate_action_rejects_full_columns() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=(
            (SEAT0_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT1_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT1_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    with pytest.raises(IllegalAction):
        rules.validate_action(state, 0, DropDisc(column=0))


def test_observation_exposes_public_board_state_and_legal_actions() -> None:
    rules = Connect4RulesEngine()
    state = rules.initial_state(Connect4Config(rows=4, columns=4, connect_length=4))

    observation = rules.observation(state, 0)

    assert observation == Connect4Observation(
        seat=0,
        board=state.board,
        current_seat=0,
        legal_actions=(
            DropDisc(column=0),
            DropDisc(column=1),
            DropDisc(column=2),
            DropDisc(column=3),
        ),
    )


def test_observation_for_a_non_active_seat_stays_public_but_has_no_legal_actions() -> None:
    rules = Connect4RulesEngine()
    state = rules.initial_state(Connect4Config(rows=4, columns=4, connect_length=4))

    observation = rules.observation(state, 1)

    assert observation == Connect4Observation(
        seat=1,
        board=state.board,
        current_seat=0,
        legal_actions=(),
    )


def test_terminal_observation_exposes_empty_legal_actions() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, SEAT1_DISC, SEAT1_DISC, EMPTY_CELL),
        ),
        current_seat=0,
    )
    terminal_state = rules.apply_action(state, 0, DropDisc(column=0)).state

    observation = rules.observation(terminal_state, 0)

    assert observation == Connect4Observation(
        seat=0,
        board=terminal_state.board,
        current_seat=0,
        legal_actions=(),
    )


def test_near_full_observation_exposes_only_remaining_playable_column() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=(
            (SEAT0_DISC, EMPTY_CELL, SEAT1_DISC, SEAT0_DISC),
            (SEAT1_DISC, SEAT0_DISC, SEAT0_DISC, SEAT1_DISC),
            (SEAT0_DISC, SEAT1_DISC, SEAT1_DISC, SEAT0_DISC),
            (SEAT1_DISC, SEAT0_DISC, SEAT0_DISC, SEAT1_DISC),
        ),
        current_seat=1,
    )

    observation = rules.observation(state, 1)

    assert observation.legal_actions == (DropDisc(column=1),)


def test_repeated_legal_actions_and_observations_are_stable() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, SEAT0_DISC, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    first_actions = rules.legal_actions(state, 0)
    second_actions = rules.legal_actions(state, 0)
    first_observation = rules.observation(state, 0)
    second_observation = rules.observation(state, 0)

    assert second_actions == first_actions
    assert second_observation == first_observation


def test_connect4_package_exports_rules_and_observation_surface() -> None:
    assert "Connect4Observation" in connect4_exports
    assert "Connect4RulesEngine" in connect4_exports


def test_apply_action_places_a_disc_in_the_lowest_available_row_and_switches_turns() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, SEAT0_DISC, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    transition = rules.apply_action(state, 0, DropDisc(column=1))

    assert transition.state == Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, SEAT0_DISC, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, SEAT0_DISC, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=1,
    )
    assert transition.events == (DiscDropped(seat=0, column=1, row=1),)
    assert transition.result is None


@pytest.mark.parametrize(
    ("state", "action", "expected_row"),
    [
        (
            Connect4State(
                board=(
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (SEAT0_DISC, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
                ),
                current_seat=0,
            ),
            DropDisc(column=2),
            3,
        ),
        (
            Connect4State(
                board=(
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (EMPTY_CELL, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
                    (SEAT0_DISC, SEAT0_DISC, EMPTY_CELL, EMPTY_CELL),
                ),
                current_seat=0,
            ),
            DropDisc(column=1),
            1,
        ),
    ],
)
def test_apply_action_emits_disc_dropped_with_the_landing_cell(
    state: Connect4State,
    action: DropDisc,
    expected_row: int,
) -> None:
    rules = Connect4RulesEngine()

    transition = rules.apply_action(state, state.current_seat, action)

    assert transition.events[0] == DiscDropped(
        seat=state.current_seat,
        column=action.column,
        row=expected_row,
    )


@pytest.mark.parametrize(
    ("state", "action", "expected_result"),
    [
        (
            Connect4State(
                board=(
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (SEAT0_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (SEAT0_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (SEAT0_DISC, SEAT1_DISC, SEAT1_DISC, EMPTY_CELL),
                ),
                current_seat=0,
            ),
            DropDisc(column=0),
            Win(seat=0),
        ),
        (
            Connect4State(
                board=(
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (SEAT1_DISC, SEAT1_DISC, SEAT1_DISC, EMPTY_CELL),
                ),
                current_seat=1,
            ),
            DropDisc(column=3),
            Win(seat=1),
        ),
        (
            Connect4State(
                board=(
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (EMPTY_CELL, EMPTY_CELL, SEAT0_DISC, SEAT1_DISC),
                    (EMPTY_CELL, SEAT0_DISC, SEAT1_DISC, SEAT1_DISC),
                    (SEAT0_DISC, SEAT1_DISC, SEAT1_DISC, SEAT1_DISC),
                ),
                current_seat=0,
            ),
            DropDisc(column=3),
            Win(seat=0),
        ),
        (
            Connect4State(
                board=(
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (SEAT0_DISC, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
                    (SEAT0_DISC, SEAT0_DISC, SEAT1_DISC, EMPTY_CELL),
                    (SEAT0_DISC, SEAT0_DISC, SEAT0_DISC, SEAT1_DISC),
                ),
                current_seat=1,
            ),
            DropDisc(column=0),
            Win(seat=1),
        ),
    ],
    ids=["vertical", "horizontal", "diagonal_rising", "diagonal_falling"],
)
def test_apply_action_detects_wins_in_all_four_directions(
    state: Connect4State,
    action: DropDisc,
    expected_result: Win,
) -> None:
    rules = Connect4RulesEngine()

    transition = rules.apply_action(state, state.current_seat, action)

    assert transition.result == expected_result
    assert transition.events[1] == WinnerDetected(winning_seat=expected_result.seat)
    assert transition.state.current_seat == state.current_seat
    assert rules.is_terminal(transition.state) is True
    assert rules.result(transition.state) == expected_result


def test_apply_action_detects_draws_and_emits_game_drawn_after_disc_dropped() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=(
            (EMPTY_CELL, SEAT0_DISC, SEAT1_DISC, SEAT1_DISC),
            (SEAT1_DISC, SEAT1_DISC, SEAT0_DISC, SEAT0_DISC),
            (SEAT0_DISC, SEAT0_DISC, SEAT1_DISC, SEAT1_DISC),
            (SEAT1_DISC, SEAT1_DISC, SEAT0_DISC, SEAT0_DISC),
        ),
        current_seat=0,
    )

    transition = rules.apply_action(state, 0, DropDisc(column=0))

    assert transition.result == Draw()
    assert transition.events == (
        DiscDropped(seat=0, column=0, row=0),
        GameDrawn(),
    )
    assert transition.state.current_seat == 0
    assert rules.is_terminal(transition.state) is True
    assert rules.result(transition.state) == Draw()


def test_result_detects_a_winning_board_without_transition_context() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT1_DISC, SEAT1_DISC, SEAT1_DISC, SEAT1_DISC),
            (SEAT0_DISC, SEAT0_DISC, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    assert rules.result(state) == Win(seat=1)
    assert rules.is_terminal(state) is True


def test_non_default_connect_length_does_not_treat_four_in_a_row_as_a_win() -> None:
    config = Connect4Config(rows=5, columns=6, connect_length=5)
    rules = Connect4RulesEngine(config)
    state = Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, SEAT0_DISC, SEAT0_DISC, SEAT0_DISC, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    assert rules.result(state) is None
    assert rules.is_terminal(state) is False


def test_non_default_connect_length_requires_five_in_a_row() -> None:
    config = Connect4Config(rows=5, columns=6, connect_length=5)
    rules = Connect4RulesEngine(config)
    state = Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT1_DISC, SEAT1_DISC, SEAT1_DISC, SEAT1_DISC, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=1,
    )

    transition = rules.apply_action(state, 1, DropDisc(column=4))

    assert transition.result == Win(seat=1)
    assert transition.events == (
        DiscDropped(seat=1, column=4, row=4),
        WinnerDetected(winning_seat=1),
    )
    assert rules.result(transition.state) == Win(seat=1)
    assert rules.is_terminal(transition.state) is True


def test_winning_terminal_states_suppress_legal_actions_and_future_moves() -> None:
    rules = Connect4RulesEngine()
    state = Connect4State(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_DISC, SEAT1_DISC, SEAT1_DISC, EMPTY_CELL),
        ),
        current_seat=0,
    )
    winning_transition = rules.apply_action(state, 0, DropDisc(column=0))

    assert rules.legal_actions(winning_transition.state, 0) == ()

    with pytest.raises(GameFinished):
        rules.validate_action(winning_transition.state, 0, DropDisc(column=1))
