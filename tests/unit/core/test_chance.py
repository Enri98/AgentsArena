"""Chance nodes and reproducible randomness (Phase 37).

The same seed must produce the same draws on any machine, and the seed must never
leak: the generator is owned by the match, not by broadcast state or config.
"""

from __future__ import annotations

import collections
import dataclasses

import pytest

from arena.core.chance import (
    ChanceRng,
    apply_chance,
    dump_chance_outcome,
    is_chance_node,
    load_chance_outcome,
    rules_engine_declares_chance,
    sample_chance,
    validate_chance_support,
)
from arena.core.exceptions import IncompleteChanceSupport, InvalidGameConfig
from arena.core.registry import GameRegistry
from arena.games import build_default_registry
from arena.testing.chance_factory import CoinOutcome, build_coin_game_definition
from arena.testing.factories import build_fake_game_bundle

# ---------------------------------------------------------------------------
# ChanceRng
# ---------------------------------------------------------------------------


def test_same_seed_reproduces_the_same_sequence() -> None:
    first, _ = ChanceRng(seed=99).draw_many(6, 20)
    second, _ = ChanceRng(seed=99).draw_many(6, 20)
    assert first == second


def test_different_seeds_diverge() -> None:
    a, _ = ChanceRng(seed=1).draw_many(1000, 10)
    b, _ = ChanceRng(seed=2).draw_many(1000, 10)
    assert a != b


def test_drawing_is_pure() -> None:
    """A draw returns the advanced generator rather than mutating in place."""

    rng = ChanceRng(seed=7)
    value, advanced = rng.draw(6)

    assert rng.counter == 0  # untouched
    assert advanced.counter > rng.counter
    assert advanced.seed == rng.seed
    assert value == rng.draw(6)[0]  # drawing again from the original repeats


def test_draw_many_matches_sequential_draws() -> None:
    rng = ChanceRng(seed=42)
    batched, after_batch = rng.draw_many(10, 4)

    values = []
    cursor = rng
    for _ in range(4):
        value, cursor = cursor.draw(10)
        values.append(value)

    assert tuple(values) == batched
    assert cursor == after_batch


def test_values_stay_in_range() -> None:
    rng = ChanceRng(seed=5)
    for _ in range(200):
        value, rng = rng.draw(6)
        assert 0 <= value < 6


@pytest.mark.parametrize("bound", [0, -1])
def test_non_positive_bound_is_rejected(bound: int) -> None:
    with pytest.raises(ValueError):
        ChanceRng(seed=1).draw(bound)


def test_negative_count_is_rejected() -> None:
    with pytest.raises(ValueError):
        ChanceRng(seed=1).draw_many(6, -1)


def test_draws_are_uniform() -> None:
    """Rejection sampling, so the die is not subtly loaded."""

    rng = ChanceRng(seed=2024)
    counts: collections.Counter[int] = collections.Counter()
    for _ in range(12_000):
        value, rng = rng.draw(6)
        counts[value] += 1

    assert set(counts) == set(range(6))
    expected = 12_000 / 6
    for face, seen in counts.items():
        assert abs(seen - expected) < expected * 0.12, f"face {face} skewed: {seen}"


def test_round_trips_through_its_payload() -> None:
    rng = ChanceRng(seed=8, counter=3)
    assert ChanceRng.load(rng.dump()) == rng
    assert rng.dump() == {"seed": 8, "counter": 3}


@pytest.mark.parametrize(
    "payload",
    [{}, {"seed": 1}, {"counter": 1}, {"seed": "x", "counter": 1}],
)
def test_malformed_payloads_are_rejected(payload: dict) -> None:
    with pytest.raises(InvalidGameConfig):
        ChanceRng.load(payload)


def test_the_generator_compares_equal_after_a_round_trip() -> None:
    rng = ChanceRng(seed=3)
    _, advanced = rng.draw(20)
    assert ChanceRng.load(advanced.dump()) == advanced
    assert ChanceRng.load(advanced.dump()).draw(20) == advanced.draw(20)


def test_repr_does_not_reveal_the_seed() -> None:
    """A seed that reached a log line or an exception message would be public."""

    rng = ChanceRng(seed=987654321987654321)
    assert "987654321987654321" not in repr(rng)


# ---------------------------------------------------------------------------
# Engine and serializer hooks
# ---------------------------------------------------------------------------


class _ChanceEngine:
    def is_chance_node(self, state: object) -> bool:
        return state == "pending"

    def sample_chance(self, state: object, rng: ChanceRng) -> tuple[int, ChanceRng]:
        return rng.draw(6)

    def apply_chance(self, state: object, outcome: int) -> str:
        return f"rolled {outcome}"


class _BadSampler(_ChanceEngine):
    def sample_chance(self, state: object, rng: ChanceRng) -> tuple[int, object]:  # type: ignore[override]
        return 1, "not a generator"


def test_games_without_hooks_are_never_at_a_chance_node() -> None:
    """Every existing caller keeps its current behaviour."""

    for definition in build_default_registry().list():
        if definition.has_chance_nodes:
            continue
        engine = definition.rules_engine
        state = engine.initial_state(definition.config_type())
        assert not rules_engine_declares_chance(engine)
        assert is_chance_node(engine, state) is False


def test_declared_hooks_are_used() -> None:
    engine = _ChanceEngine()
    assert rules_engine_declares_chance(engine)
    assert is_chance_node(engine, "pending") is True
    assert is_chance_node(engine, "settled") is False

    outcome, rng = sample_chance(engine, "pending", ChanceRng(seed=1))
    assert 0 <= outcome < 6
    assert rng.counter > 0
    assert apply_chance(engine, "pending", outcome) == f"rolled {outcome}"


def test_sampling_must_return_a_generator() -> None:
    with pytest.raises(TypeError):
        sample_chance(_BadSampler(), "pending", ChanceRng(seed=1))


def test_resolving_without_support_is_an_error() -> None:
    bundle = build_fake_game_bundle()
    engine = bundle.definition.rules_engine
    with pytest.raises(IncompleteChanceSupport):
        sample_chance(engine, bundle.initial_state, ChanceRng(seed=1))
    with pytest.raises(IncompleteChanceSupport):
        apply_chance(engine, bundle.initial_state, 3)
    with pytest.raises(IncompleteChanceSupport):
        dump_chance_outcome(bundle.definition.serializer, 3)


def test_outcomes_round_trip_through_the_serializer() -> None:
    serializer = build_coin_game_definition().serializer
    payload = dump_chance_outcome(serializer, CoinOutcome(face=1))
    assert payload == {"face": 1}
    assert load_chance_outcome(serializer, payload) == CoinOutcome(face=1)


# ---------------------------------------------------------------------------
# The declaration gate
# ---------------------------------------------------------------------------


def _definition(**overrides: object) -> object:
    return dataclasses.replace(build_fake_game_bundle().definition, **overrides)


def test_games_without_chance_need_no_hooks() -> None:
    validate_chance_support(_definition())  # does not raise


def test_declaring_chance_without_hooks_is_rejected() -> None:
    with pytest.raises(IncompleteChanceSupport) as exc:
        validate_chance_support(_definition(has_chance_nodes=True))

    missing = exc.value.details["missing"]
    assert "rules_engine.is_chance_node" in missing
    assert "rules_engine.sample_chance" in missing
    assert "rules_engine.apply_chance" in missing
    assert "serializer.dump_chance_outcome" in missing
    assert "serializer.load_chance_outcome" in missing


def test_an_engine_alone_is_not_enough() -> None:
    """Without serializer hooks a chance turn could be recorded but never replayed."""

    with pytest.raises(IncompleteChanceSupport) as exc:
        validate_chance_support(
            _definition(has_chance_nodes=True, rules_engine=_ChanceEngine())
        )
    assert exc.value.details["missing"] == [
        "serializer.dump_chance_outcome",
        "serializer.load_chance_outcome",
    ]


def test_fully_implemented_chance_game_validates() -> None:
    validate_chance_support(build_coin_game_definition())


def test_registry_rejects_an_unbacked_chance_declaration() -> None:
    registry = GameRegistry()
    with pytest.raises(IncompleteChanceSupport):
        registry.register(_definition(has_chance_nodes=True))
    assert registry.list() == ()


def test_deterministic_games_declare_no_chance_nodes() -> None:
    deterministic = {"connect4", "tictactoe", "nim"}
    for definition in build_default_registry().list():
        if definition.game_id in deterministic:
            assert definition.has_chance_nodes is False
