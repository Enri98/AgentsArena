"""Chance nodes and reproducible randomness (Phase 37).

v1 games were strictly deterministic. A chance node is a point in a game where
no seat acts and a random outcome is resolved instead — a deal, a roll, a draw.

Chance is nature's action
-------------------------
Resolving a chance node is split in two, mirroring how a seat acts:

* ``sample_chance(state, rng) -> (outcome, rng)`` draws an outcome. This is the
  only place randomness enters, and only a live match ever calls it.
* ``apply_chance(state, outcome) -> TransitionResult`` applies an outcome and,
  like ``apply_action``, revalidates it defensively.

The outcome is recorded in the transcript's chance turn. **Replay applies the
recorded outcome and never re-rolls**, so validating a transcript needs no seed.

The seed never leaves the match
-------------------------------
The generator lives on ``LocalMatch`` — never in game state and never in config.
Both are broadcast: config goes to both seats in ``welcome`` and is embedded in
every snapshot, and state is the body of every ``post_snapshot``. A seed in either
would let a seat run the generator forward and predict every future roll.
Outcomes reveal nothing about the seed, because a draw is a hash of
``(seed, counter)``.

Why not widen ``RulesEngine.current_seat`` to ``Seat | None``
-------------------------------------------------------------
Callers check ``is_chance_node`` first — the same shape as the ``is_terminal``
guard used before asking whose turn it is. ``arena.match`` drains chance nodes
as part of stepping, so a live match is never left resting at one.

As with ``public_view``, the hooks are detected rather than added to the
``RulesEngine`` and ``Serializer`` Protocols: those are ``@runtime_checkable``,
so a new member would make every existing implementation fail ``isinstance``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from arena.core.exceptions import IncompleteChanceSupport, InvalidGameConfig

#: Hooks a rules engine defines to take part in chance resolution.
IS_CHANCE_NODE_METHOD = "is_chance_node"
SAMPLE_CHANCE_METHOD = "sample_chance"
APPLY_CHANCE_METHOD = "apply_chance"

#: Hooks a serializer defines so chance outcomes can be recorded and replayed.
DUMP_CHANCE_OUTCOME_METHOD = "dump_chance_outcome"
LOAD_CHANCE_OUTCOME_METHOD = "load_chance_outcome"

_ENGINE_HOOKS = (IS_CHANCE_NODE_METHOD, SAMPLE_CHANCE_METHOD, APPLY_CHANCE_METHOD)
_SERIALIZER_HOOKS = (DUMP_CHANCE_OUTCOME_METHOD, LOAD_CHANCE_OUTCOME_METHOD)

_WORD_BITS = 64
_WORD_MAX = 1 << _WORD_BITS

#: Seeds and counters are hashed as 16-byte unsigned integers.
SEED_BITS = 128
_SEED_MAX = 1 << SEED_BITS


@dataclass(frozen=True)
class ChanceRng:
    """A reproducible random source addressed by ``(seed, counter)``.

    Drawing does not mutate: it returns the value plus the advanced generator, so
    sampling stays pure.

    The same ``(seed, counter)`` yields the same value on any machine and any
    Python build, because the draw is a hash rather than an interpreter-internal
    PRNG state.

    The generator belongs to the match, never to game state or config — both are
    broadcast (see the module docstring). ``repr`` hides the seed so it cannot
    leak through a log line or an exception message.
    """

    seed: int = field(repr=False)
    counter: int = 0

    def __post_init__(self) -> None:
        # Validated here rather than at the first draw: a bad seed that only
        # fails mid-match would be reported against whichever seat just acted.
        for name, value in (("seed", self.seed), ("counter", self.counter)):
            if type(value) is not int or not 0 <= value < _SEED_MAX:
                raise ValueError(
                    f"ChanceRng {name} must be an int in [0, 2**{SEED_BITS}), "
                    f"got a {type(value).__name__}."
                )

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
        """JSON-friendly form. It contains the seed: never put it on the wire."""

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


def _require_hook(obj: object, name: str, owner: str) -> None:
    if not _has_hook(obj, name):
        raise IncompleteChanceSupport(
            f"This {owner} has no {name} hook, so a chance node cannot be resolved.",
            details={owner: type(obj).__name__, "missing": name},
        )


def rules_engine_declares_chance(rules_engine: object) -> bool:
    """Whether a rules engine implements every chance hook."""

    return all(_has_hook(rules_engine, name) for name in _ENGINE_HOOKS)


def is_chance_node(rules_engine: Any, state: Any) -> bool:
    """Whether ``state`` is awaiting a chance outcome rather than a seat.

    Always ``False`` for a game without chance hooks, so every existing caller
    keeps its current behaviour.
    """

    if not _has_hook(rules_engine, IS_CHANCE_NODE_METHOD):
        return False
    return bool(rules_engine.is_chance_node(state))


def sample_chance(rules_engine: Any, state: Any, rng: ChanceRng) -> tuple[Any, ChanceRng]:
    """Draw an outcome for the pending chance node; return it and the next rng.

    Only a live match calls this. Replay never samples.
    """

    _require_hook(rules_engine, SAMPLE_CHANCE_METHOD, "rules_engine")
    outcome, next_rng = rules_engine.sample_chance(state, rng)
    if not isinstance(next_rng, ChanceRng):
        raise TypeError(
            f"{type(rules_engine).__name__}.sample_chance must return "
            f"(outcome, ChanceRng), got {type(next_rng).__name__} as the generator."
        )
    return outcome, next_rng


def apply_chance(rules_engine: Any, state: Any, outcome: Any) -> Any:
    """Apply one chance outcome, returning a ``TransitionResult``.

    The engine revalidates the outcome, exactly as ``apply_action`` revalidates
    an action: an outcome read back from a transcript is untrusted input.
    """

    _require_hook(rules_engine, APPLY_CHANCE_METHOD, "rules_engine")
    return rules_engine.apply_chance(state, outcome)


def dump_chance_outcome(serializer: Any, outcome: Any) -> dict[str, Any]:
    """Serialize a chance outcome for its transcript turn."""

    _require_hook(serializer, DUMP_CHANCE_OUTCOME_METHOD, "serializer")
    return dict(serializer.dump_chance_outcome(outcome))


def load_chance_outcome(serializer: Any, payload: dict[str, Any]) -> Any:
    """Rehydrate a recorded chance outcome for replay."""

    _require_hook(serializer, LOAD_CHANCE_OUTCOME_METHOD, "serializer")
    return serializer.load_chance_outcome(payload)


def validate_chance_support(definition: Any) -> None:
    """Check that a game's chance declaration and implementation agree.

    A game declaring ``has_chance_nodes=True`` without every hook would fail the
    first time it reached a chance node — or record a turn it could not replay —
    so the inconsistency is rejected at registration.
    """

    if not getattr(definition, "has_chance_nodes", False):
        # The converse matters too: hooks without the flag register, get no
        # generator, and the first chance node then deadlocks the match — every
        # action is refused while nothing ever rolls.
        if _has_hook(definition.rules_engine, IS_CHANCE_NODE_METHOD):
            raise IncompleteChanceSupport(
                f"Game '{definition.game_id}' implements "
                f"rules_engine.{IS_CHANCE_NODE_METHOD} but does not declare "
                f"has_chance_nodes=True, so its matches would get no generator.",
                details={"game_id": definition.game_id, "missing": ["has_chance_nodes"]},
            )
        return

    missing = [
        f"rules_engine.{name}"
        for name in _ENGINE_HOOKS
        if not _has_hook(definition.rules_engine, name)
    ] + [
        f"serializer.{name}"
        for name in _SERIALIZER_HOOKS
        if not _has_hook(definition.serializer, name)
    ]

    if missing:
        raise IncompleteChanceSupport(
            f"Game '{definition.game_id}' declares has_chance_nodes=True but does not "
            f"implement: {', '.join(missing)}. A match would stall at the first "
            f"chance node.",
            details={"game_id": definition.game_id, "missing": missing},
        )


__all__: Sequence[str] = [
    "APPLY_CHANCE_METHOD",
    "DUMP_CHANCE_OUTCOME_METHOD",
    "IS_CHANCE_NODE_METHOD",
    "LOAD_CHANCE_OUTCOME_METHOD",
    "SAMPLE_CHANCE_METHOD",
    "SEED_BITS",
    "ChanceRng",
    "apply_chance",
    "dump_chance_outcome",
    "is_chance_node",
    "load_chance_outcome",
    "rules_engine_declares_chance",
    "sample_chance",
    "validate_chance_support",
]
