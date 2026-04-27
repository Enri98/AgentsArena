"""Local in-process policy helpers for pure match execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from arena.core.types import Seat
from arena.match.local_match import (
    ActionT,
    ConfigT,
    LocalMatch,
    ObservationT,
    ResultT,
    StateT,
    apply_match_action,
)


class Policy(Protocol[ObservationT, ActionT]):
    """Select an action from a player-facing observation."""

    def select_action(self, observation: ObservationT) -> ActionT:
        """Return the next action to apply for the observed seat."""


def apply_policy_turn(
    match: LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT],
    policies: Mapping[Seat, Policy[ObservationT, ActionT]],
) -> LocalMatch[ConfigT, StateT, ActionT, ObservationT, ResultT]:
    """Ask the active seat's policy for an action and apply one turn."""

    seat = match.rules_engine.current_seat(match.state)
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
