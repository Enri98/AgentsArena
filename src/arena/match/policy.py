"""Local in-process policy helpers for pure match execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol, TypeVar

from arena.core.actions import Action
from arena.core.observations import Observation
from arena.core.simultaneous import acting_seats
from arena.core.types import Seat
from arena.match.local_match import (
    ActionT,
    ConfigT,
    LocalMatch,
    ObservationT,
    ResultT,
    StateT,
    apply_match_action,
    apply_match_joint_action,
)

# A policy consumes observations and produces actions.
_ObservationContraT = TypeVar("_ObservationContraT", bound=Observation, contravariant=True)
_ActionCoT = TypeVar("_ActionCoT", bound=Action, covariant=True)


class Policy(Protocol[_ObservationContraT, _ActionCoT]):
    """Select an action from a player-facing observation."""

    def select_action(self, observation: _ObservationContraT) -> _ActionCoT:
        """Return the next action to apply for the observed seat."""


def apply_policy_turn(
    match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
    policies: Mapping[Seat, Policy[ObservationT, ActionT]],
) -> LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Ask the acting seat's policy for an action and apply one turn.

    At a joint node (Phase 41) every acting seat is asked, each from its own
    observation of the same state, and the round is applied at once.
    """

    seats = acting_seats(match.rules_engine, match.state)
    if len(seats) > 1:
        actions = {
            seat: policies[seat].select_action(
                match.rules_engine.observation(match.state, seat)
            )
            for seat in seats
        }
        return apply_match_joint_action(match, actions)
    seat = seats[0] if seats else match.rules_engine.current_seat(match.state)
    policy = policies[seat]
    observation = match.rules_engine.observation(match.state, seat)
    action = policy.select_action(observation)
    return apply_match_action(match, seat, action)


def run_local_match(
    match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
    policies: Mapping[Seat, Policy[ObservationT, ActionT]],
) -> LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Run a match to terminal state using in-process seat policies."""

    while not match.rules_engine.is_terminal(match.state):
        match = apply_policy_turn(match, policies)
    return match


__all__: Sequence[str] = [
    "Policy",
    "apply_policy_turn",
    "run_local_match",
]
