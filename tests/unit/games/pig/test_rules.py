"""Tests for the Pig rules engine, including its chance hooks."""

from __future__ import annotations

import collections

import pytest

from arena.core.chance import ChanceRng
from arena.core.exceptions import (
    ChanceResolutionError,
    GameFinished,
    IllegalAction,
    WrongPlayer,
)
from arena.core.results import Win
from arena.games.pig import (
    HOLD,
    ROLL,
    DieRoll,
    PigConfig,
    PigDieRolled,
    PigHeld,
    PigMatchWon,
    PigMove,
    PigRollChosen,
    PigRulesEngine,
    PigState,
)

ENGINE = PigRulesEngine()
ROLL_MOVE = PigMove(choice=ROLL)
HOLD_MOVE = PigMove(choice=HOLD)


def _state(**overrides: object) -> PigState:
    fields = dict(
        scores=(0, 0), current_seat=0, turn_total=0, roll_pending=False, target_score=50
    )
    fields.update(overrides)
    return PigState(**fields)  # type: ignore[arg-type]


def test_initial_state() -> None:
    state = ENGINE.initial_state(PigConfig(target_score=30))
    assert state == _state(target_score=30)
    assert not ENGINE.is_chance_node(state)
    assert not ENGINE.is_terminal(state)


def test_a_turn_must_open_with_a_roll() -> None:
    state = _state()
    assert ENGINE.legal_actions(state, 0) == (ROLL_MOVE,)
    with pytest.raises(IllegalAction):
        ENGINE.validate_action(state, 0, HOLD_MOVE)


def test_both_choices_are_legal_with_a_turn_total() -> None:
    assert ENGINE.legal_actions(_state(turn_total=7), 0) == (ROLL_MOVE, HOLD_MOVE)


def test_the_idle_seat_has_no_actions_and_cannot_act() -> None:
    assert ENGINE.legal_actions(_state(), 1) == ()
    with pytest.raises(WrongPlayer):
        ENGINE.apply_action(_state(), 1, ROLL_MOVE)


def test_rolling_creates_a_chance_node() -> None:
    transition = ENGINE.apply_action(_state(), 0, ROLL_MOVE)

    assert transition.state == _state(roll_pending=True)
    assert transition.events == (PigRollChosen(seat=0),)
    assert transition.result is None
    assert ENGINE.is_chance_node(transition.state)


def test_no_seat_can_act_while_the_die_is_in_the_air() -> None:
    pending = _state(roll_pending=True)
    assert ENGINE.legal_actions(pending, 0) == ()
    with pytest.raises(IllegalAction):
        ENGINE.apply_action(pending, 0, ROLL_MOVE)


def test_a_roll_of_two_to_six_adds_to_the_turn_total() -> None:
    transition = ENGINE.apply_chance(_state(roll_pending=True, turn_total=4), DieRoll(face=5))

    assert transition.state == _state(turn_total=9)
    assert transition.events == (PigDieRolled(seat=0, face=5, busted=False, turn_total=9),)


def test_a_one_busts_the_turn_and_passes_it() -> None:
    transition = ENGINE.apply_chance(
        _state(roll_pending=True, turn_total=12, scores=(10, 3)), DieRoll(face=1)
    )

    assert transition.state == _state(scores=(10, 3), current_seat=1)
    assert transition.events == (PigDieRolled(seat=0, face=1, busted=True, turn_total=0),)


@pytest.mark.parametrize("face", [0, 7, -1])
def test_impossible_faces_are_rejected(face: int) -> None:
    with pytest.raises(ChanceResolutionError):
        ENGINE.apply_chance(_state(roll_pending=True), DieRoll(face=face))


def test_an_outcome_without_a_pending_roll_is_rejected() -> None:
    with pytest.raises(ChanceResolutionError):
        ENGINE.apply_chance(_state(), DieRoll(face=3))


def test_holding_banks_and_passes_the_turn() -> None:
    transition = ENGINE.apply_action(_state(turn_total=8, scores=(10, 20)), 0, HOLD_MOVE)

    assert transition.state == _state(scores=(18, 20), current_seat=1)
    assert transition.events == (PigHeld(seat=0, banked=8, score=18),)
    assert transition.result is None


def test_holding_to_the_target_wins() -> None:
    transition = ENGINE.apply_action(
        _state(current_seat=1, turn_total=15, scores=(40, 38)), 1, HOLD_MOVE
    )

    assert transition.state.scores == (40, 53)
    assert transition.events[-1] == PigMatchWon(winner_seat=1)
    assert transition.result == Win(seat=1)
    assert ENGINE.result(transition.state) == Win(seat=1)
    assert ENGINE.is_terminal(transition.state)
    assert not ENGINE.is_chance_node(transition.state)
    assert ENGINE.legal_actions(transition.state, 1) == ()
    with pytest.raises(GameFinished):
        ENGINE.apply_action(transition.state, 1, ROLL_MOVE)


def test_sampled_faces_are_a_fair_die() -> None:
    rng = ChanceRng(seed=11)
    counts: collections.Counter[int] = collections.Counter()
    state = _state(roll_pending=True)
    for _ in range(6000):
        roll, rng = ENGINE.sample_chance(state, rng)
        counts[roll.face] += 1

    assert set(counts) == {1, 2, 3, 4, 5, 6}
    for face, seen in counts.items():
        assert abs(seen - 1000) < 150, f"face {face} skewed: {seen}"


def test_observation_is_public_and_carries_legal_actions() -> None:
    obs = ENGINE.observation(_state(turn_total=6, scores=(12, 30)), 1)

    assert obs.seat == 1
    assert obs.scores == (12, 30)
    assert obs.current_seat == 0
    assert obs.turn_total == 6
    assert obs.target_score == 50
    assert obs.legal_actions == ()  # seat 1 is not to move


def test_state_invariants() -> None:
    with pytest.raises(ValueError):
        _state(scores=(0,))
    with pytest.raises(ValueError):
        _state(current_seat=2)
    with pytest.raises(ValueError):
        _state(turn_total=-1)
    with pytest.raises(ValueError):
        _state(roll_pending=1)
    with pytest.raises(ValueError):
        PigMove(choice="pass")
