"""Tests for the Nim rules engine."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from arena.core.actions import Action
from arena.core.exceptions import GameFinished, IllegalAction, WrongPlayer
from arena.core.results import Win
from arena.games.nim import (
    NimConfig,
    NimMatchWon,
    NimObjectsTaken,
    NimObservation,
    NimRulesEngine,
    NimState,
    TakeObjects,
)
from arena.games.nim import __all__ as nim_exports


@dataclass(frozen=True)
class FakeAction(Action):
    """Non-Nim action used for validation tests."""


def test_initial_state_builds_all_piles_at_max_size() -> None:
    rules = NimRulesEngine()
    config = NimConfig(num_piles=3, max_pile_size=5)

    state = rules.initial_state(config)

    assert state == NimState(piles=(5, 5, 5), current_seat=0)


def test_initial_state_seat_0_goes_first() -> None:
    rules = NimRulesEngine()
    config = NimConfig()

    state = rules.initial_state(config)

    assert rules.current_seat(state) == 0


def test_current_seat_reflects_state() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(3, 5, 7), current_seat=1)

    assert rules.current_seat(state) == 1


def test_legal_actions_cover_all_take_amounts_for_each_pile() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(2, 3), current_seat=0)

    actions = rules.legal_actions(state, 0)

    expected = (
        TakeObjects(pile_index=0, count=1),
        TakeObjects(pile_index=0, count=2),
        TakeObjects(pile_index=1, count=1),
        TakeObjects(pile_index=1, count=2),
        TakeObjects(pile_index=1, count=3),
    )
    assert actions == expected


def test_legal_actions_skip_empty_piles() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(0, 3), current_seat=0)

    actions = rules.legal_actions(state, 0)

    # pile 0 is empty — no actions for it
    for action in actions:
        assert action.pile_index != 0
    assert len(actions) == 3  # take 1, 2, or 3 from pile 1


def test_legal_actions_empty_for_wrong_seat() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(3, 5, 7), current_seat=0)

    assert rules.legal_actions(state, 1) == ()


def test_legal_actions_empty_for_terminal_state() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(0, 0, 0), current_seat=0)

    assert rules.is_terminal(state) is True
    assert rules.legal_actions(state, 0) == ()


def test_apply_action_takes_objects_and_switches_seat() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(3, 5, 7), current_seat=0)

    transition = rules.apply_action(state, 0, TakeObjects(pile_index=1, count=3))

    assert transition.state == NimState(piles=(3, 2, 7), current_seat=1)
    assert transition.result is None
    assert transition.events == (
        NimObjectsTaken(seat=0, pile_index=1, count=3, remaining=[3, 2, 7]),
    )


def test_apply_action_emits_win_and_result_when_last_object_taken() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(0, 0, 1), current_seat=0)

    transition = rules.apply_action(state, 0, TakeObjects(pile_index=2, count=1))

    assert transition.result == Win(seat=0)
    assert transition.state.piles == (0, 0, 0)
    assert len(transition.events) == 2
    assert isinstance(transition.events[0], NimObjectsTaken)
    assert transition.events[1] == NimMatchWon(winner_seat=0)


def test_seat_1_wins_by_taking_last_object() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(0, 1, 0), current_seat=1)

    transition = rules.apply_action(state, 1, TakeObjects(pile_index=1, count=1))

    assert transition.result == Win(seat=1)
    assert transition.events[1] == NimMatchWon(winner_seat=1)


def test_is_terminal_false_for_non_empty_piles() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(1, 0, 0), current_seat=0)

    assert rules.is_terminal(state) is False


def test_is_terminal_true_when_all_piles_zero() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(0, 0, 0), current_seat=0)

    assert rules.is_terminal(state) is True


def test_result_returns_none_for_non_terminal() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(1, 2, 3), current_seat=0)

    assert rules.result(state) is None


def test_validate_action_rejects_finished_game() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(0, 0, 0), current_seat=0)

    with pytest.raises(GameFinished):
        rules.validate_action(state, 0, TakeObjects(pile_index=0, count=1))


def test_validate_action_rejects_wrong_player() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(3, 5, 7), current_seat=0)

    with pytest.raises(WrongPlayer):
        rules.validate_action(state, 1, TakeObjects(pile_index=0, count=1))


def test_validate_action_rejects_wrong_action_type() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(3, 5, 7), current_seat=0)

    with pytest.raises(IllegalAction):
        rules.validate_action(state, 0, FakeAction())


def test_validate_action_rejects_out_of_range_pile_index() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(3, 5, 7), current_seat=0)

    with pytest.raises(IllegalAction):
        rules.validate_action(state, 0, TakeObjects(pile_index=3, count=1))


def test_validate_action_rejects_taking_more_than_pile_has() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(3, 5, 7), current_seat=0)

    with pytest.raises(IllegalAction):
        rules.validate_action(state, 0, TakeObjects(pile_index=0, count=4))


def test_validate_action_rejects_taking_from_empty_pile() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(0, 5, 7), current_seat=0)

    with pytest.raises(IllegalAction):
        rules.validate_action(state, 0, TakeObjects(pile_index=0, count=1))


def test_observation_exposes_piles_current_seat_and_legal_actions() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(1, 2), current_seat=0)

    obs = rules.observation(state, 0)

    assert isinstance(obs, NimObservation)
    assert obs.piles == (1, 2)
    assert obs.current_seat == 0
    assert obs.seat == 0
    assert len(obs.legal_actions) == 3  # (0,1), (1,1), (1,2)


def test_observation_for_non_active_seat_has_no_legal_actions() -> None:
    rules = NimRulesEngine()
    state = NimState(piles=(3, 5, 7), current_seat=0)

    obs = rules.observation(state, 1)

    assert obs.seat == 1
    assert obs.legal_actions == ()


def test_full_game_seat0_wins_nim_sum_strategy() -> None:
    """Seat 0 plays nim-sum optimal; seat 1 plays first-legal. Seat 0 should win."""
    rules = NimRulesEngine()
    config = NimConfig(num_piles=3, max_pile_size=3)
    state = rules.initial_state(config)
    # piles = (3, 3, 3), nim-sum = 3^3^3 = 3 — seat 0 can win

    move_count = 0
    while not rules.is_terminal(state):
        seat = rules.current_seat(state)
        legal = rules.legal_actions(state, seat)
        assert legal, "non-terminal state must have legal actions"
        state = rules.apply_action(state, seat, legal[0]).state
        move_count += 1
        assert move_count < 100, "match did not terminate"

    result = rules.result(state)
    assert isinstance(result, Win)


def test_nim_package_exports_core_surface() -> None:
    assert "NimRulesEngine" in nim_exports
    assert "NimState" in nim_exports
    assert "TakeObjects" in nim_exports
    assert "NimConfig" in nim_exports
    assert "NimObservation" in nim_exports
