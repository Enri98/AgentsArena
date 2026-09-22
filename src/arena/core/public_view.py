"""Public-view helpers (Phase 36 Slice 1).

For a perfect-information game there is no distinction between "the authoritative
state" and "what a spectator may see" — the public view *is* the state. Games
with hidden information must say so by declaring
``GameDefinition.has_hidden_information`` and implementing the redaction hooks
named below.

These are free functions rather than new members on the ``RulesEngine`` and
``Serializer`` Protocols. Both are ``@runtime_checkable``, and a runtime-checkable
Protocol tests for method *presence*: adding a member would make every existing
engine and serializer fail ``isinstance`` until it implemented the new method,
which is the opposite of an additive change. Games opt in by defining the hook;
everything else falls back to the full state.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from arena.core.exceptions import IncompletePublicView
from arena.core.serializer import JSONMapping

#: Hook a rules engine defines to expose the strictly-public view of a state.
PUBLIC_STATE_METHOD = "public_state"

#: Hooks a serializer defines to move that public view across the boundary.
DUMP_PUBLIC_STATE_METHOD = "dump_public_state"
LOAD_PUBLIC_STATE_METHOD = "load_public_state"


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


def validate_public_view(definition: Any) -> None:
    """Check that a game's public-view declaration and implementation agree.

    A game declaring ``has_hidden_information=True`` whose engine and serializer
    do not redact would broadcast private state to every seat and spectator — a
    silent information leak. Fail loudly at registration instead.
    """

    if not getattr(definition, "has_hidden_information", False):
        return

    missing: list[str] = []
    if not rules_engine_declares_public_state(definition.rules_engine):
        missing.append(f"rules_engine.{PUBLIC_STATE_METHOD}")
    if not _has_hook(definition.serializer, DUMP_PUBLIC_STATE_METHOD):
        missing.append(f"serializer.{DUMP_PUBLIC_STATE_METHOD}")
    if not _has_hook(definition.serializer, LOAD_PUBLIC_STATE_METHOD):
        missing.append(f"serializer.{LOAD_PUBLIC_STATE_METHOD}")

    if missing:
        raise IncompletePublicView(
            f"Game '{definition.game_id}' declares has_hidden_information=True but does "
            f"not implement: {', '.join(missing)}. Without these the full state would be "
            f"broadcast to every seat.",
            details={"game_id": definition.game_id, "missing": missing},
        )


__all__: Sequence[str] = [
    "DUMP_PUBLIC_STATE_METHOD",
    "LOAD_PUBLIC_STATE_METHOD",
    "PUBLIC_STATE_METHOD",
    "dump_public_state",
    "load_public_state",
    "public_state",
    "rules_engine_declares_public_state",
    "serializer_declares_public_state",
    "validate_public_view",
]
