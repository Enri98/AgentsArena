"""Simultaneous moves (Phase 41).

In a sequential game exactly one seat acts at a time (``current_seat``). In a
simultaneous round several seats act at once, each without seeing the others'
choice: rock-paper-scissors, a sealed bid.

A simultaneous round is a joint turn
------------------------------------
An engine that has simultaneous rounds defines two hooks:

* ``acting_seats(state) -> tuple[Seat, ...]``: the seats that act now. One seat
  is an ordinary sequential turn (``apply_action``); two or more make a joint
  node, which only :func:`apply_joint_action` resolves.
* ``apply_joint_action(state, actions) -> TransitionResult``: resolve the round
  from every acting seat's action at once.

Each action is checked with the engine's ordinary ``validate_action(state,
seat, action)`` when it arrives, so a seat can be told at once that its move
is illegal. Nothing is applied until every acting seat has a valid action.
**No seat's choice is ever part of state or of a transcript before the others
have chosen**: the round is committed as one turn carrying every action. So a
joint turn needs no redaction; the actions are revealed together, as at a
table.

``current_seat`` keeps its signature. At a joint node it returns the lowest
acting seat and means nothing more; callers ask :func:`acting_seats`.

As with chance nodes, the hooks are detected rather than added to the
``RulesEngine`` Protocol, which is ``@runtime_checkable``: a new member would
make every existing implementation fail ``isinstance``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from arena.core.chance import is_chance_node
from arena.core.exceptions import IncompleteSimultaneousSupport, WrongPlayer
from arena.core.types import Seat

ACTING_SEATS_METHOD = "acting_seats"
APPLY_JOINT_ACTION_METHOD = "apply_joint_action"

_ENGINE_HOOKS = (ACTING_SEATS_METHOD, APPLY_JOINT_ACTION_METHOD)


def _has_hook(obj: object, name: str) -> bool:
    return callable(getattr(obj, name, None))


def rules_engine_declares_simultaneous(rules_engine: object) -> bool:
    """Whether a rules engine implements both simultaneous-move hooks."""

    return all(_has_hook(rules_engine, name) for name in _ENGINE_HOOKS)


def acting_seats(rules_engine: Any, state: Any) -> tuple[Seat, ...]:
    """The seats that act in ``state``, in seat order.

    Empty at a terminal state or a chance node (nobody acts). For an engine
    without the hook, the one ``current_seat``.
    """

    if rules_engine.is_terminal(state) or is_chance_node(rules_engine, state):
        return ()
    hook = getattr(rules_engine, ACTING_SEATS_METHOD, None)
    if not callable(hook):
        return (rules_engine.current_seat(state),)
    seats = tuple(hook(state))
    if not seats or list(seats) != sorted(set(seats)):
        raise WrongPlayer(
            "acting_seats must name at least one seat, in seat order, without repeats.",
            details={"acting_seats": list(seats)},
        )
    return seats


def is_joint_node(rules_engine: Any, state: Any) -> bool:
    """Whether several seats act at once in ``state``."""

    return len(acting_seats(rules_engine, state)) > 1


def apply_joint_action(
    rules_engine: Any, state: Any, actions: Mapping[Seat, Any]
) -> Any:
    """Resolve a joint node from one action per acting seat.

    Revalidates everything, as ``apply_action`` does: the seats must be exactly
    the acting seats, and each action must pass ``validate_action``.
    """

    seats = acting_seats(rules_engine, state)
    if len(seats) < 2:
        raise WrongPlayer(
            "No joint node is pending: act with apply_action.",
            details={"acting_seats": list(seats)},
        )
    if sorted(actions) != list(seats):
        raise WrongPlayer(
            "A joint action needs exactly one action per acting seat.",
            details={"acting_seats": list(seats), "given": sorted(actions)},
        )
    for seat in seats:
        rules_engine.validate_action(state, seat, actions[seat])
    ordered = {seat: actions[seat] for seat in seats}
    return getattr(rules_engine, APPLY_JOINT_ACTION_METHOD)(state, ordered)


def validate_simultaneous_support(definition: Any) -> None:
    """Refuse a definition whose flag and hooks disagree.

    Checked at registration: a game declaring simultaneous moves without the
    hooks would stall at its first joint node, and hooks without the flag would
    be a game the server does not know to treat as simultaneous.
    """

    declared = bool(getattr(definition, "has_simultaneous_moves", False))
    engine = definition.rules_engine
    implemented = rules_engine_declares_simultaneous(engine)
    if declared and not implemented:
        missing = [name for name in _ENGINE_HOOKS if not _has_hook(engine, name)]
        raise IncompleteSimultaneousSupport(
            f"Game {definition.game_id!r} declares simultaneous moves but its rules "
            f"engine lacks {', '.join(missing)}.",
            details={"game_id": definition.game_id, "missing": missing},
        )
    if implemented and not declared:
        raise IncompleteSimultaneousSupport(
            f"Game {definition.game_id!r} implements simultaneous-move hooks but does not "
            "set has_simultaneous_moves.",
            details={"game_id": definition.game_id},
        )


__all__: Sequence[str] = [
    "ACTING_SEATS_METHOD",
    "APPLY_JOINT_ACTION_METHOD",
    "acting_seats",
    "apply_joint_action",
    "is_joint_node",
    "rules_engine_declares_simultaneous",
    "validate_simultaneous_support",
]
