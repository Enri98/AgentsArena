"""Chance nodes and reproducible randomness (Phase 37 Slice 1).

v1 games were strictly deterministic. A chance node is a point in a game where
no seat acts and the rules engine resolves a random outcome instead — a deal, a
roll, a draw.

Two properties make this safe to put on the wire:

* **Chance is a first-class transition.** Resolving a chance node produces a
  ``TransitionResult`` like any other, emits domain events describing what
  happened, and is recorded as its own step in the transcript. Replay reads the
  recorded outcome and never re-rolls.
* **Randomness is a value, not a generator.** ``ChanceRng`` is a frozen
  ``(seed, counter)`` pair that lives in serialized game state. It round-trips
  through ``dump_state``/``load_state`` and compares equal, which transcript
  validation requires — it compares post-state snapshots exactly on every turn.
  A ``random.Random`` would not survive that: its state is a 625-int tuple whose
  meaning is tied to the interpreter.

Why not widen ``RulesEngine.current_seat`` to ``Seat | None``
-------------------------------------------------------------
The phase spec floated returning ``None`` at a chance node, which would mean
auditing 27 call sites. Instead ``current_seat`` keeps its contract and callers
check ``is_chance_node`` first — the same shape as the ``is_terminal`` guard the
codebase already uses before asking whose turn it is.

This is not a weakening, because ``arena.match`` **drains chance nodes as part of
stepping**: a match is never left resting at one. Chance nodes are real in the
rules engine and real in the transcript, but no observer of a settled match ever
sees a state where nobody is to move.

As with ``public_view``, the hooks are detected on the engine rather than added
to the ``RulesEngine`` Protocol: it is ``@runtime_checkable``, so a new member
would make every existing engine fail ``isinstance`` until it implemented one.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from arena.core.exceptions import IncompleteChanceSupport, InvalidGameConfig

#: Hooks a rules engine defines to take part in chance resolution.
IS_CHANCE_NODE_METHOD = "is_chance_node"
RESOLVE_CHANCE_METHOD = "resolve_chance"

_WORD_BITS = 64
_WORD_MAX = 1 << _WORD_BITS


@dataclass(frozen=True)
class ChanceRng:
    """A reproducible random source addressed by ``(seed, counter)``.

    Drawing does not mutate: it returns the value plus the advanced generator, so
    a state transition stays pure and the generator can live inside frozen game
    state.

    The same ``(seed, counter)`` yields the same value on any machine and any
    Python build, because the draw is a hash rather than an interpreter-internal
    PRNG state.
    """

    seed: int
    counter: int = 0

    def _block(self, counter: int) -> int:
        digest = hashlib.blake2b(
            self.seed.to_bytes(16, "big", signed=False)
            + counter.to_bytes(16, "big", signed=False),
            digest_size=8,
        ).digest()
        return int.from_bytes(digest, "big")

    def draw(self, bound: int) -> tuple[int, "ChanceRng"]:
        """Draw a uniform integer in ``[0, bound)`` and return the next generator.

        Rejection-sampled, so the result is unbiased rather than merely close to
        uniform — a die that is 0.0001% loaded is still a loaded die, and the
        cost of getting it right is one comparison.
        """

        if bound <= 0:
            raise ValueError(f"draw bound must be positive, got {bound}")

        # Largest multiple of `bound` that fits in a word; values at or above it
        # would over-represent the low residues.
        limit = _WORD_MAX - (_WORD_MAX % bound)
        counter = self.counter
        while True:
            raw = self._block(counter)
            counter += 1
            if raw < limit:
                return raw % bound, ChanceRng(seed=self.seed, counter=counter)

    def draw_many(self, bound: int, count: int) -> tuple[tuple[int, ...], "ChanceRng"]:
        """Draw ``count`` values in order, returning them with the final generator."""

        if count < 0:
            raise ValueError(f"draw count must not be negative, got {count}")
        values: list[int] = []
        rng = self
        for _ in range(count):
            value, rng = rng.draw(bound)
            values.append(value)
        return tuple(values), rng

    def dump(self) -> dict[str, int]:
        """JSON-friendly form for embedding in serialized state."""

        return {"seed": self.seed, "counter": self.counter}

    @classmethod
    def load(cls, payload: dict[str, Any]) -> "ChanceRng":
        try:
            return cls(seed=int(payload["seed"]), counter=int(payload["counter"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidGameConfig(
                "Chance generator payload must carry integer 'seed' and 'counter'.",
                details={"payload": payload},
            ) from exc


def _has_hook(obj: object, name: str) -> bool:
    return callable(getattr(obj, name, None))


def rules_engine_declares_chance(rules_engine: object) -> bool:
    """Whether a rules engine implements both chance hooks."""

    return _has_hook(rules_engine, IS_CHANCE_NODE_METHOD) and _has_hook(
        rules_engine, RESOLVE_CHANCE_METHOD
    )


def is_chance_node(rules_engine: Any, state: Any) -> bool:
    """Whether ``state`` is awaiting a chance resolution rather than a seat.

    Always ``False`` for a game without chance hooks, so every existing caller
    keeps its current behaviour.
    """

    if not _has_hook(rules_engine, IS_CHANCE_NODE_METHOD):
        return False
    return bool(rules_engine.is_chance_node(state))


def resolve_chance(rules_engine: Any, state: Any) -> Any:
    """Resolve one pending chance node, returning a ``TransitionResult``.

    Raises if the engine does not support chance; callers gate on
    :func:`is_chance_node` first.
    """

    if not _has_hook(rules_engine, RESOLVE_CHANCE_METHOD):
        raise IncompleteChanceSupport(
            "This rules engine has no resolve_chance hook, so a chance node "
            "cannot be resolved.",
            details={"rules_engine": type(rules_engine).__name__},
        )
    return rules_engine.resolve_chance(state)


def validate_chance_support(definition: Any) -> None:
    """Check that a game's chance declaration and implementation agree.

    A game declaring ``has_chance_nodes=True`` whose engine cannot resolve one
    would hang the match loop the first time it reached a chance node, so the
    inconsistency is rejected at registration.
    """

    if not getattr(definition, "has_chance_nodes", False):
        return

    missing: list[str] = []
    if not _has_hook(definition.rules_engine, IS_CHANCE_NODE_METHOD):
        missing.append(f"rules_engine.{IS_CHANCE_NODE_METHOD}")
    if not _has_hook(definition.rules_engine, RESOLVE_CHANCE_METHOD):
        missing.append(f"rules_engine.{RESOLVE_CHANCE_METHOD}")

    if missing:
        raise IncompleteChanceSupport(
            f"Game '{definition.game_id}' declares has_chance_nodes=True but does not "
            f"implement: {', '.join(missing)}. A match would stall at the first "
            f"chance node.",
            details={"game_id": definition.game_id, "missing": missing},
        )


__all__: Sequence[str] = [
    "IS_CHANCE_NODE_METHOD",
    "RESOLVE_CHANCE_METHOD",
    "ChanceRng",
    "is_chance_node",
    "resolve_chance",
    "rules_engine_declares_chance",
    "validate_chance_support",
]
