"""Public-view and per-seat view helpers (Phase 36 Slice 1, Phase 38 Slice 1).

For a perfect-information game there is no distinction between "the authoritative
state", "what a seat may see", and "what a spectator may see" — every view *is*
the state. Games with hidden information must say so by declaring
``GameDefinition.has_hidden_information`` and implementing the redaction hooks
named below.

A *viewer* is either a seat (an ``int``) or ``None``, meaning the public — a
spectator, or anything published outside the match. Everything that crosses the
boundary to a viewer goes through one of the ``*_for_viewer`` helpers:

* state — ``dump_state_for_seat`` / ``dump_public_state``
* config — ``dump_config_for_seat`` / ``dump_public_config``
* chance outcomes — ``dump_chance_outcome_for_seat`` / ``dump_public_chance_outcome``

State hooks are **required** for a hidden-information game, and so are the
chance-outcome hooks if it also has chance nodes: without them the full value
would reach every viewer. Config hooks are optional. Config holds game parameters,
never secrets (a seed in config is exactly the leak Phase 37 designed out), so the
default is to show it whole.

These are free functions rather than new members on the ``RulesEngine`` and
``Serializer`` Protocols. Both are ``@runtime_checkable``, and a runtime-checkable
Protocol tests for method *presence*: adding a member would make every existing
engine and serializer fail ``isinstance`` until it implemented the new method,
which is the opposite of an additive change. Games opt in by defining the hook;
everything else falls back to the full value.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from arena.core.exceptions import IncompletePublicView
from arena.core.serializer import JSONMapping
from arena.core.types import Seat

#: Hook a rules engine defines to expose the strictly-public view of a state.
PUBLIC_STATE_METHOD = "public_state"

#: Hooks a serializer defines to move that public view across the boundary.
DUMP_PUBLIC_STATE_METHOD = "dump_public_state"
LOAD_PUBLIC_STATE_METHOD = "load_public_state"

#: Serializer hook for one seat's view of the state (Phase 38).
DUMP_STATE_FOR_SEAT_METHOD = "dump_state_for_seat"

#: Optional serializer hooks for config a viewer may not see in full (Phase 38).
DUMP_CONFIG_FOR_SEAT_METHOD = "dump_config_for_seat"
DUMP_PUBLIC_CONFIG_METHOD = "dump_public_config"

#: Serializer hooks for chance outcomes a viewer may not see in full (Phase 38).
DUMP_CHANCE_OUTCOME_FOR_SEAT_METHOD = "dump_chance_outcome_for_seat"
DUMP_PUBLIC_CHANCE_OUTCOME_METHOD = "dump_public_chance_outcome"

#: ``None`` as a viewer means the public: a spectator, or a published transcript.
Viewer = Seat | None


class FullView:
    """Sentinel for "no redaction": the authoritative, full view.

    Only the server (and archived-transcript tooling) should ever hold it for a
    hidden-information game. A distinct type rather than a magic value, so it can
    never be confused with seat ``0`` or with ``None`` (the public).
    """

    _instance: "FullView | None" = None

    def __new__(cls) -> "FullView":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "FULL_VIEW"


FULL_VIEW = FullView()

#: Seats a viewer may name. Two-seat today; widen with N-player.
VIEWER_SEATS: tuple[Seat, ...] = (0, 1)


def check_viewer(viewer: object) -> None:
    """Reject anything that is not ``None`` or a real seat id.

    Without this, ``-1`` would index a per-seat tuple from the end and hand a
    viewer the *last* seat's private data, and ``True`` (an ``int`` subclass)
    would be treated as seat 1.
    """

    if viewer is None:
        return
    if type(viewer) is not int or viewer not in VIEWER_SEATS:
        raise ValueError(f"A viewer is a seat in {VIEWER_SEATS} or None, not {viewer!r}.")


def _has_hook(obj: object, name: str) -> bool:
    return callable(getattr(obj, name, None))


def rules_engine_declares_public_state(rules_engine: object) -> bool:
    """Whether a rules engine implements its own public-state redaction."""

    return _has_hook(rules_engine, PUBLIC_STATE_METHOD)


def serializer_declares_public_state(serializer: object) -> bool:
    """Whether a serializer implements both public-state boundary hooks."""

    return _has_hook(serializer, DUMP_PUBLIC_STATE_METHOD) and _has_hook(
        serializer, LOAD_PUBLIC_STATE_METHOD
    )


def public_state(rules_engine: Any, state: Any) -> Any:
    """Return the strictly-public view of ``state``.

    Falls back to ``observation(state, seat=0)`` for games that do not redact —
    valid precisely because every seat sees the same thing in a
    perfect-information game.
    """

    if rules_engine_declares_public_state(rules_engine):
        return rules_engine.public_state(state)
    return rules_engine.observation(state, 0)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------


def dump_public_state(serializer: Any, state: Any) -> JSONMapping:
    """Serialize the spectator-safe view of ``state``.

    Falls back to ``dump_state`` for games without hidden information, where the
    two are the same payload by definition.
    """

    if _has_hook(serializer, DUMP_PUBLIC_STATE_METHOD):
        return serializer.dump_public_state(state)
    return serializer.dump_state(state)


def load_public_state(serializer: Any, payload: JSONMapping) -> Any:
    """Rehydrate a payload produced by :func:`dump_public_state`."""

    if _has_hook(serializer, LOAD_PUBLIC_STATE_METHOD):
        return serializer.load_public_state(payload)
    return serializer.load_state(payload)


def dump_state_for_seat(serializer: Any, state: Any, seat: Seat) -> JSONMapping:
    """Serialize what ``seat`` is entitled to see of ``state``.

    Falls back to ``dump_state``, which is only correct for a game without
    hidden information — :func:`validate_public_view` rejects a hidden-information
    game that lacks the hook.
    """

    check_viewer(seat)
    if seat is None:
        raise ValueError("dump_state_for_seat needs a seat; use dump_public_state for None.")
    if _has_hook(serializer, DUMP_STATE_FOR_SEAT_METHOD):
        return serializer.dump_state_for_seat(state, seat)
    return serializer.dump_state(state)


def dump_state_for_viewer(serializer: Any, state: Any, viewer: Viewer) -> JSONMapping:
    """``dump_state_for_seat`` for a seat, ``dump_public_state`` for the public."""

    check_viewer(viewer)
    if viewer is None:
        return dump_public_state(serializer, state)
    return dump_state_for_seat(serializer, state, viewer)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def dump_config_for_seat(serializer: Any, config: Any, seat: Seat) -> JSONMapping:
    """Serialize what ``seat`` may see of the config; the whole config by default."""

    check_viewer(seat)
    if _has_hook(serializer, DUMP_CONFIG_FOR_SEAT_METHOD):
        return serializer.dump_config_for_seat(config, seat)
    return serializer.dump_config(config)


def dump_public_config(serializer: Any, config: Any) -> JSONMapping:
    """Serialize what the public may see of the config; the whole config by default."""

    if _has_hook(serializer, DUMP_PUBLIC_CONFIG_METHOD):
        return serializer.dump_public_config(config)
    return serializer.dump_config(config)


def dump_config_for_viewer(serializer: Any, config: Any, viewer: Viewer) -> JSONMapping:
    check_viewer(viewer)
    if viewer is None:
        return dump_public_config(serializer, config)
    return dump_config_for_seat(serializer, config, viewer)


# ---------------------------------------------------------------------------
# Chance outcomes
# ---------------------------------------------------------------------------


def dump_chance_outcome_for_viewer(
    serializer: Any, outcome: Any, viewer: Viewer
) -> JSONMapping:
    """Serialize what ``viewer`` may see of a chance outcome.

    A deal or an opening roll in a hidden-information game is private: each seat
    may see only its own share. Falls back to the full outcome, which
    :func:`validate_public_view` only permits for a game without hidden
    information.
    """

    check_viewer(viewer)
    if viewer is None and _has_hook(serializer, DUMP_PUBLIC_CHANCE_OUTCOME_METHOD):
        return serializer.dump_public_chance_outcome(outcome)
    if viewer is not None and _has_hook(serializer, DUMP_CHANCE_OUTCOME_FOR_SEAT_METHOD):
        return serializer.dump_chance_outcome_for_seat(outcome, viewer)
    return serializer.dump_chance_outcome(outcome)


# ---------------------------------------------------------------------------
# The declaration gate
# ---------------------------------------------------------------------------


def validate_public_view(definition: Any) -> None:
    """Check that a game's view declarations and implementation agree.

    A game declaring ``has_hidden_information=True`` whose engine and serializer
    do not redact would broadcast private state to every seat and spectator — a
    silent information leak. Fail loudly at registration instead.
    """

    if not getattr(definition, "has_hidden_information", False):
        return

    serializer = definition.serializer
    missing: list[str] = []
    if not rules_engine_declares_public_state(definition.rules_engine):
        missing.append(f"rules_engine.{PUBLIC_STATE_METHOD}")
    for name in (DUMP_PUBLIC_STATE_METHOD, LOAD_PUBLIC_STATE_METHOD, DUMP_STATE_FOR_SEAT_METHOD):
        if not _has_hook(serializer, name):
            missing.append(f"serializer.{name}")
    if getattr(definition, "has_chance_nodes", False):
        for name in (DUMP_CHANCE_OUTCOME_FOR_SEAT_METHOD, DUMP_PUBLIC_CHANCE_OUTCOME_METHOD):
            if not _has_hook(serializer, name):
                missing.append(f"serializer.{name}")

    if missing:
        raise IncompletePublicView(
            f"Game '{definition.game_id}' declares has_hidden_information=True but does "
            f"not implement: {', '.join(missing)}. Without these the full state would be "
            f"broadcast to every seat.",
            details={"game_id": definition.game_id, "missing": missing},
        )


__all__: Sequence[str] = [
    "DUMP_CHANCE_OUTCOME_FOR_SEAT_METHOD",
    "DUMP_CONFIG_FOR_SEAT_METHOD",
    "DUMP_PUBLIC_CHANCE_OUTCOME_METHOD",
    "DUMP_PUBLIC_CONFIG_METHOD",
    "DUMP_PUBLIC_STATE_METHOD",
    "DUMP_STATE_FOR_SEAT_METHOD",
    "FULL_VIEW",
    "FullView",
    "LOAD_PUBLIC_STATE_METHOD",
    "PUBLIC_STATE_METHOD",
    "VIEWER_SEATS",
    "Viewer",
    "check_viewer",
    "dump_chance_outcome_for_viewer",
    "dump_config_for_seat",
    "dump_config_for_viewer",
    "dump_public_config",
    "dump_public_state",
    "dump_state_for_seat",
    "dump_state_for_viewer",
    "load_public_state",
    "public_state",
    "rules_engine_declares_public_state",
    "serializer_declares_public_state",
    "validate_public_view",
]
