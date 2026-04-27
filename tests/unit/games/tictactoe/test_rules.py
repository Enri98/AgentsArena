"""Tests for the Tic-Tac-Toe rules-engine scaffold."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from arena.core.actions import Action
from arena.core.exceptions import GameFinished, IllegalAction, WrongPlayer
from arena.core.results import Draw, Win
from arena.games.tictactoe import (
    EMPTY_CELL,
    SEAT0_MARK,
    SEAT1_MARK,
    GameDrawn,
    MarkPlaced,
    PlaceMark,
    TicTacToeConfig,
    TicTacToeObservation,
    TicTacToeRulesEngine,
    TicTacToeState,
    WinnerDetected,
)
from arena.games.tictactoe import __all__ as tictactoe_exports


@dataclass(frozen=True)
class FakeAction(Action):
    """Non-Tic-Tac-Toe action used for validation tests."""


def test_initial_state_builds_an_empty_immutable_board_from_config() -> None:
    rules = TicTacToeRulesEngine()
    config = TicTacToeConfig()

    state = rules.initial_state(config)

    assert state == TicTacToeState(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )


def test_current_seat_returns_the_state_seat_without_hidden_context() -> None:
    rules = TicTacToeRulesEngine()
    state = TicTacToeState(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (SEAT0_MARK, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=1,
    )

    assert rules.current_seat(state) == 1


def test_legal_actions_return_row_major_empty_cells() -> None:
    rules = TicTacToeRulesEngine()
    state = TicTacToeState(
        board=(
            (SEAT0_MARK, EMPTY_CELL, SEAT1_MARK),
            (EMPTY_CELL, SEAT1_MARK, EMPTY_CELL),
            (SEAT0_MARK, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    assert rules.legal_actions(state, 0) == (
        PlaceMark(row=0, column=1),
        PlaceMark(row=1, column=0),
        PlaceMark(row=1, column=2),
        PlaceMark(row=2, column=1),
        PlaceMark(row=2, column=2),
    )


def test_legal_actions_return_empty_for_wrong_seat() -> None:
    rules = TicTacToeRulesEngine()
    state = rules.initial_state(TicTacToeConfig())

    assert rules.legal_actions(state, 1) == ()


def test_legal_actions_return_empty_for_terminal_states() -> None:
    rules = TicTacToeRulesEngine()
    state = TicTacToeState(
        board=(
            (SEAT0_MARK, SEAT0_MARK, SEAT0_MARK),
            (SEAT1_MARK, SEAT1_MARK, SEAT0_MARK),
            (SEAT0_MARK, SEAT1_MARK, SEAT1_MARK),
        ),
        current_seat=0,
    )

    assert rules.is_terminal(state) is True
    assert rules.result(state) == Win(seat=0)
    assert rules.legal_actions(state, 0) == ()


def test_validate_action_rejects_moves_after_game_finished() -> None:
    rules = TicTacToeRulesEngine()
    state = TicTacToeState(
        board=(
            (SEAT0_MARK, SEAT0_MARK, SEAT0_MARK),
            (SEAT1_MARK, SEAT1_MARK, SEAT0_MARK),
            (SEAT0_MARK, SEAT1_MARK, SEAT1_MARK),
        ),
        current_seat=0,
    )

    with pytest.raises(GameFinished):
        rules.validate_action(state, 0, PlaceMark(row=2, column=0))


def test_validate_action_rejects_wrong_player() -> None:
    rules = TicTacToeRulesEngine()
    state = rules.initial_state(TicTacToeConfig())

    with pytest.raises(WrongPlayer):
        rules.validate_action(state, 1, PlaceMark(row=0, column=0))


def test_validate_action_rejects_wrong_action_type() -> None:
    rules = TicTacToeRulesEngine()
    state = rules.initial_state(TicTacToeConfig())

    with pytest.raises(IllegalAction):
        rules.validate_action(state, 0, FakeAction())


def test_validate_action_rejects_out_of_bounds_cells() -> None:
    rules = TicTacToeRulesEngine()
    state = rules.initial_state(TicTacToeConfig())

    with pytest.raises(IllegalAction):
        rules.validate_action(state, 0, PlaceMark(row=3, column=0))

    with pytest.raises(IllegalAction):
        rules.validate_action(state, 0, PlaceMark(row=0, column=3))


def test_validate_action_rejects_occupied_cells() -> None:
    rules = TicTacToeRulesEngine()
    state = TicTacToeState(
        board=(
            (SEAT0_MARK, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    with pytest.raises(IllegalAction):
        rules.validate_action(state, 0, PlaceMark(row=0, column=0))


def test_observation_exposes_public_board_state_and_legal_actions() -> None:
    rules = TicTacToeRulesEngine()
    state = rules.initial_state(TicTacToeConfig())

    observation = rules.observation(state, 0)

    assert observation == TicTacToeObservation(
        seat=0,
        board=state.board,
        current_seat=0,
        legal_actions=tuple(
            PlaceMark(row=row, column=column) for row in range(3) for column in range(3)
        ),
    )


def test_observation_for_a_non_active_seat_stays_public_but_has_no_legal_actions() -> None:
    rules = TicTacToeRulesEngine()
    state = rules.initial_state(TicTacToeConfig())

    observation = rules.observation(state, 1)

    assert observation == TicTacToeObservation(
        seat=1,
        board=state.board,
        current_seat=0,
        legal_actions=(),
    )


def test_terminal_observation_exposes_empty_legal_actions() -> None:
    rules = TicTacToeRulesEngine()
    state = TicTacToeState(
        board=(
            (SEAT0_MARK, SEAT0_MARK, EMPTY_CELL),
            (SEAT1_MARK, SEAT1_MARK, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )
    terminal_state = rules.apply_action(state, 0, PlaceMark(row=0, column=2)).state

    observation = rules.observation(terminal_state, 0)

    assert observation == TicTacToeObservation(
        seat=0,
        board=terminal_state.board,
        current_seat=0,
        legal_actions=(),
    )


def test_repeated_legal_actions_and_observations_are_stable() -> None:
    rules = TicTacToeRulesEngine()
    state = TicTacToeState(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, SEAT1_MARK, EMPTY_CELL),
            (SEAT0_MARK, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    first_actions = rules.legal_actions(state, 0)
    second_actions = rules.legal_actions(state, 0)
    first_observation = rules.observation(state, 0)
    second_observation = rules.observation(state, 0)

    assert second_actions == first_actions
    assert second_observation == first_observation


def test_tictactoe_package_exports_rules_and_observation_surface() -> None:
    assert "TicTacToeObservation" in tictactoe_exports
    assert "TicTacToeRulesEngine" in tictactoe_exports


def test_apply_action_places_a_mark_in_the_selected_cell_and_switches_turns() -> None:
    rules = TicTacToeRulesEngine()
    state = TicTacToeState(
        board=(
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
            (EMPTY_CELL, SEAT1_MARK, EMPTY_CELL),
            (SEAT0_MARK, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    transition = rules.apply_action(state, 0, PlaceMark(row=0, column=1))

    assert transition.state == TicTacToeState(
        board=(
            (EMPTY_CELL, SEAT0_MARK, EMPTY_CELL),
            (EMPTY_CELL, SEAT1_MARK, EMPTY_CELL),
            (SEAT0_MARK, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=1,
    )
    assert transition.events == (MarkPlaced(seat=0, row=0, column=1),)
    assert transition.result is None


@pytest.mark.parametrize(
    ("state", "action", "expected_result"),
    [
        (
            TicTacToeState(
                board=(
                    (SEAT0_MARK, SEAT0_MARK, EMPTY_CELL),
                    (SEAT1_MARK, SEAT1_MARK, EMPTY_CELL),
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                ),
                current_seat=0,
            ),
            PlaceMark(row=0, column=2),
            Win(seat=0),
        ),
        (
            TicTacToeState(
                board=(
                    (SEAT0_MARK, SEAT1_MARK, EMPTY_CELL),
                    (SEAT0_MARK, SEAT1_MARK, EMPTY_CELL),
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                ),
                current_seat=0,
            ),
            PlaceMark(row=2, column=0),
            Win(seat=0),
        ),
        (
            TicTacToeState(
                board=(
                    (SEAT0_MARK, SEAT1_MARK, EMPTY_CELL),
                    (SEAT1_MARK, SEAT0_MARK, EMPTY_CELL),
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                ),
                current_seat=0,
            ),
            PlaceMark(row=2, column=2),
            Win(seat=0),
        ),
        (
            TicTacToeState(
                board=(
                    (EMPTY_CELL, EMPTY_CELL, SEAT0_MARK),
                    (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
                    (SEAT0_MARK, SEAT1_MARK, EMPTY_CELL),
                ),
                current_seat=0,
            ),
            PlaceMark(row=1, column=1),
            Win(seat=0),
        ),
    ],
    ids=["row", "column", "diagonal_main", "diagonal_anti"],
)
def test_apply_action_detects_wins_in_all_four_directions(
    state: TicTacToeState,
    action: PlaceMark,
    expected_result: Win,
) -> None:
    rules = TicTacToeRulesEngine()

    transition = rules.apply_action(state, state.current_seat, action)

    assert transition.result == expected_result
    assert transition.events[1] == WinnerDetected(winning_seat=expected_result.seat)
    assert transition.state.current_seat == state.current_seat
    assert rules.is_terminal(transition.state) is True
    assert rules.result(transition.state) == expected_result


def test_apply_action_detects_draws_and_emits_game_drawn_after_mark_placed() -> None:
    rules = TicTacToeRulesEngine()
    state = TicTacToeState(
        board=(
            (SEAT0_MARK, SEAT1_MARK, SEAT0_MARK),
            (SEAT0_MARK, SEAT1_MARK, SEAT1_MARK),
            (SEAT1_MARK, EMPTY_CELL, SEAT0_MARK),
        ),
        current_seat=0,
    )

    transition = rules.apply_action(state, 0, PlaceMark(row=2, column=1))

    assert transition.result == Draw()
    assert transition.events == (
        MarkPlaced(seat=0, row=2, column=1),
        GameDrawn(),
    )
    assert transition.state.current_seat == 0
    assert rules.is_terminal(transition.state) is True
    assert rules.result(transition.state) == Draw()


def test_result_detects_a_winning_board_without_transition_context() -> None:
    rules = TicTacToeRulesEngine()
    state = TicTacToeState(
        board=(
            (SEAT0_MARK, SEAT0_MARK, SEAT0_MARK),
            (SEAT1_MARK, SEAT1_MARK, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )

    assert rules.result(state) == Win(seat=0)
    assert rules.is_terminal(state) is True


def test_winning_terminal_states_suppress_legal_actions_and_future_moves() -> None:
    rules = TicTacToeRulesEngine()
    state = TicTacToeState(
        board=(
            (SEAT0_MARK, SEAT0_MARK, EMPTY_CELL),
            (SEAT1_MARK, SEAT1_MARK, EMPTY_CELL),
            (EMPTY_CELL, EMPTY_CELL, EMPTY_CELL),
        ),
        current_seat=0,
    )
    winning_transition = rules.apply_action(state, 0, PlaceMark(row=0, column=2))

    assert rules.legal_actions(winning_transition.state, 0) == ()

    with pytest.raises(GameFinished):
        rules.validate_action(winning_transition.state, 0, PlaceMark(row=1, column=2))
