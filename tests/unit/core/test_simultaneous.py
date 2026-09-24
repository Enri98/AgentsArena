"""The simultaneous-move primitive (Phase 41)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from arena.core.exceptions import IncompleteSimultaneousSupport, WrongPlayer
from arena.core.registry import GameRegistry
from arena.core.simultaneous import (
    acting_seats,
    apply_joint_action,
    is_joint_node,
    validate_simultaneous_support,
)
from arena.games import build_default_registry

REGISTRY = build_default_registry()
RPS = REGISTRY.get("rps")
NIM = REGISTRY.get("nim")


def test_a_sequential_engine_acts_with_its_current_seat() -> None:
    state = NIM.rules_engine.initial_state(NIM.config_type())
    assert acting_seats(NIM.rules_engine, state) == (NIM.rules_engine.current_seat(state),)
    assert not is_joint_node(NIM.rules_engine, state)


def test_nobody_acts_at_a_terminal_state() -> None:
    engine = RPS.rules_engine
    state = engine.initial_state(RPS.config_type(target_wins=1))
    from arena.games.rps import Throw

    done = apply_joint_action(engine, state, {0: Throw("rock"), 1: Throw("scissors")}).state
    assert acting_seats(engine, done) == ()


def test_a_joint_action_is_refused_where_one_seat_acts() -> None:
    state = NIM.rules_engine.initial_state(NIM.config_type())
    action = NIM.rules_engine.legal_actions(state, 0)[0]
    with pytest.raises(WrongPlayer):
        apply_joint_action(NIM.rules_engine, state, {0: action, 1: action})


def test_every_action_of_a_joint_turn_is_validated() -> None:
    from arena.core.exceptions import IllegalAction
    from arena.games.pig import PigMove
    from arena.games.rps import Throw

    engine = RPS.rules_engine
    state = engine.initial_state(RPS.config_type())
    with pytest.raises(IllegalAction):
        apply_joint_action(engine, state, {0: Throw("rock"), 1: PigMove(choice="roll")})


class _BadEngine:
    """acting_seats out of order."""

    def __init__(self, seats):  # type: ignore[no-untyped-def]
        self.seats = seats

    def is_terminal(self, state) -> bool:  # type: ignore[no-untyped-def]
        return False

    def acting_seats(self, state):  # type: ignore[no-untyped-def]
        return self.seats

    def apply_joint_action(self, state, actions):  # type: ignore[no-untyped-def]
        raise AssertionError


@pytest.mark.parametrize("seats", [(), (1, 0), (0, 0)])
def test_acting_seats_must_be_ordered_and_distinct(seats: tuple) -> None:
    with pytest.raises(WrongPlayer):
        acting_seats(_BadEngine(seats), object())


def test_the_flag_and_the_hooks_must_agree() -> None:
    with pytest.raises(IncompleteSimultaneousSupport):
        validate_simultaneous_support(replace(RPS, has_simultaneous_moves=False))
    with pytest.raises(IncompleteSimultaneousSupport):
        validate_simultaneous_support(replace(NIM, has_simultaneous_moves=True))
    with pytest.raises(IncompleteSimultaneousSupport):
        GameRegistry().register(replace(NIM, has_simultaneous_moves=True))
