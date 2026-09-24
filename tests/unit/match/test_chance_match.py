"""Chance turns in a local match (Phase 37 Slice 3).

The generator is owned by the match. Snapshots, transcripts, and events carry
only outcomes, so nothing a seat or spectator receives reveals the seed, and
replay applies recorded outcomes instead of re-rolling.
"""

from __future__ import annotations

import copy
import json

import pytest

from arena.core.exceptions import ChanceResolutionError
from arena.games.connect4 import Connect4Config, Connect4GameDefinition
from arena.match import (
    apply_match_action,
    apply_match_chance,
    dump_match_transcript,
    start_match,
    start_replay_match,
    validate_match_transcript,
)
from arena.testing.chance_factory import (
    CoinGameConfig,
    CoinMove,
    CoinOutcome,
    build_coin_game_definition,
)

#: Distinctive enough that finding its digits anywhere would not be a fluke.
SEED = 0xC0FFEE_5EED_DEAD_BEEF_1234_5678_9ABC


def _play(seed: int | None, *, max_turns: int = 6):
    definition = build_coin_game_definition()
    match = start_match(definition, CoinGameConfig(max_turns=max_turns), seed=seed)
    while not match.rules_engine.is_terminal(match.state):
        seat = match.rules_engine.current_seat(match.state)
        match = apply_match_action(match, seat, CoinMove())
    return match


def test_an_opening_chance_node_is_resolved_before_any_seat_acts() -> None:
    match = start_match(build_coin_game_definition(), CoinGameConfig(), seed=SEED)

    assert [turn.kind for turn in match.turns] == ["chance"]
    opening = match.turns[0]
    assert opening.seat is None and opening.action is None
    assert isinstance(opening.outcome, CoinOutcome)
    assert opening.events[0].face == opening.outcome.face
    assert not match.rules_engine.is_chance_node(match.state)


def test_an_action_and_the_chance_it_triggers_are_separate_turns() -> None:
    match = _play(SEED, max_turns=3)

    # opening flip, then (move, flip) twice, then the final move ends the game.
    assert [turn.kind for turn in match.turns] == [
        "chance", "action", "chance", "action", "chance", "action",
    ]


def test_the_same_seed_reproduces_the_same_transcript() -> None:
    assert dump_match_transcript(_play(SEED)) == dump_match_transcript(_play(SEED))


def test_different_seeds_produce_different_rolls() -> None:
    flips = {_play(seed, max_turns=20).state.flips for seed in range(5)}
    assert len(flips) > 1


def test_an_unseeded_match_mints_a_secret_seed() -> None:
    """No predictable default: two unseeded matches almost surely diverge."""

    a = _play(None, max_turns=40)
    b = _play(None, max_turns=40)
    assert a.rng is not None and b.rng is not None
    assert a.rng.seed != b.rng.seed
    assert a.state.flips != b.state.flips


def test_deterministic_games_have_no_generator() -> None:
    match = start_match(Connect4GameDefinition, Connect4Config(), seed=SEED)
    assert match.rng is None


# ---------------------------------------------------------------------------
# The seed is not derivable from anything a seat receives
# ---------------------------------------------------------------------------


def _seed_fragments() -> list[str]:
    return [str(SEED), hex(SEED), hex(SEED)[2:], f"{SEED:x}".upper()]


def test_the_seed_appears_in_no_snapshot_transcript_or_event() -> None:
    match = _play(SEED)
    definition = match.definition

    dumped = json.dumps(
        {
            "transcript": dump_match_transcript(match),
            "observations": [
                definition.serializer.dump_observation(
                    match.rules_engine.observation(turn.post_state, seat)
                )
                for turn in match.turns
                for seat in (0, 1)
            ],
        }
    )

    for fragment in _seed_fragments():
        assert fragment not in dumped
    assert "seed" not in dumped
    assert "counter" not in dumped


def test_the_seed_is_not_in_the_match_repr() -> None:
    match = _play(SEED)
    text = repr(match)
    for fragment in _seed_fragments():
        assert fragment not in text


def test_state_carries_no_generator() -> None:
    """The v2 draft put the generator in state, which every snapshot broadcasts."""

    match = _play(SEED)
    for turn in match.turns:
        assert set(turn.post_snapshot.state) == {"turn", "max_turns", "flip_pending", "flips"}


# ---------------------------------------------------------------------------
# Replay never re-rolls
# ---------------------------------------------------------------------------


def test_a_transcript_validates_without_the_seed() -> None:
    payload = dump_match_transcript(_play(SEED))
    loaded = validate_match_transcript(build_coin_game_definition(), payload)

    chance_turns = [turn for turn in loaded.turns if turn.kind == "chance"]
    assert chance_turns
    assert all(isinstance(turn.outcome, CoinOutcome) for turn in chance_turns)


def test_replay_applies_the_recorded_outcome() -> None:
    """Flip every recorded outcome consistently and replay still validates.

    A replay that re-rolled from a seed could not reproduce outcomes the seed
    never produced; one that applies recorded outcomes does.
    """

    payload = dump_match_transcript(_play(SEED))
    for turn in payload["turns"]:
        if turn["kind"] == "chance":
            turn["outcome"]["face"] = 1 - turn["outcome"]["face"]
            turn["events"][0]["payload"]["face"] = turn["outcome"]["face"]
    # post_snapshot.flips mirror every flip so far; rebuild them.
    flips: list[int] = []
    for turn in payload["turns"]:
        if turn["kind"] == "chance":
            flips.append(turn["outcome"]["face"])
        turn["post_snapshot"]["state"]["flips"] = list(flips)

    validate_match_transcript(build_coin_game_definition(), payload)


def test_an_outcome_that_disagrees_with_its_snapshot_is_rejected() -> None:
    payload = dump_match_transcript(_play(SEED))
    tampered = copy.deepcopy(payload)
    first_chance = next(t for t in tampered["turns"] if t["kind"] == "chance")
    first_chance["outcome"]["face"] = 1 - first_chance["outcome"]["face"]

    with pytest.raises(ValueError):
        validate_match_transcript(build_coin_game_definition(), tampered)


def test_an_impossible_outcome_is_revalidated_by_the_engine() -> None:
    payload = dump_match_transcript(_play(SEED))
    first_chance = next(t for t in payload["turns"] if t["kind"] == "chance")
    first_chance["outcome"]["face"] = 7

    with pytest.raises(ValueError, match="A coin lands on 0 or 1") as exc:
        validate_match_transcript(build_coin_game_definition(), payload)
    assert isinstance(exc.value.__cause__, ChanceResolutionError)


def test_a_chance_turn_without_an_outcome_is_rejected() -> None:
    payload = dump_match_transcript(_play(SEED))
    first_chance = next(t for t in payload["turns"] if t["kind"] == "chance")
    first_chance["outcome"] = None

    with pytest.raises(ValueError, match="must carry its outcome"):
        validate_match_transcript(build_coin_game_definition(), payload)


def test_a_dropped_chance_turn_is_detected() -> None:
    payload = dump_match_transcript(_play(SEED))
    payload["turns"] = [t for i, t in enumerate(payload["turns"]) if i != 0]

    with pytest.raises(ValueError):
        validate_match_transcript(build_coin_game_definition(), payload)


# ---------------------------------------------------------------------------
# Replay-mode guards
# ---------------------------------------------------------------------------


def test_a_replay_match_waits_at_chance_nodes() -> None:
    match = start_replay_match(build_coin_game_definition(), CoinGameConfig())
    assert match.turns == ()
    assert match.rules_engine.is_chance_node(match.state)

    with pytest.raises(ChanceResolutionError):
        apply_match_action(match, 0, CoinMove())

    match = apply_match_chance(match, CoinOutcome(face=1))
    assert match.state.flips == (1,)
    assert match.turns[-1].kind == "chance"


def test_no_outcome_can_be_applied_when_none_is_pending() -> None:
    match = start_match(build_coin_game_definition(), CoinGameConfig(), seed=SEED)
    with pytest.raises(ChanceResolutionError):
        apply_match_chance(match, CoinOutcome(face=0))


# ---------------------------------------------------------------------------
# The shared game contract
# ---------------------------------------------------------------------------


def test_the_coin_game_passes_the_chance_contract() -> None:
    from types import SimpleNamespace

    from arena.testing import assert_chance_contract

    assert_chance_contract(SimpleNamespace(definition=build_coin_game_definition()))


# ---------------------------------------------------------------------------
# Forged shapes (adversarial review of Phase 37)
# ---------------------------------------------------------------------------


def _forge(mutate):
    payload = dump_match_transcript(_play(SEED))
    mutate(payload)
    return payload


def _first(payload, kind):
    return next(t for t in payload["turns"] if t["kind"] == kind)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda p: _first(p, "chance").update(seat=0, action={"type": "move"}),
         "no seat and no action"),
        (lambda p: _first(p, "action").update(outcome={"face": 1}), "no chance outcome"),
        (lambda p: p.update(schema_version=1), "predates chance turns"),
        (lambda p: p.update(schema_version=999), "schema_version 999"),
        (lambda p: _first(p, "chance").update(kind="dice"), "unknown turn kind"),
        (lambda p: p.update(view="seat"), "must name its viewer_seat"),
        (lambda p: p.update(schema_version=2, view="public"), "no views"),
        # Drop the final (chance, action) pair: the match now ends right after an
        # action that led to a chance node, with the roll missing.
        (lambda p: p.update(turns=p["turns"][:-2]), "pending chance node"),
    ],
)
def test_forged_transcripts_are_rejected(mutate, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_match_transcript(build_coin_game_definition(), _forge(mutate))


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda e: e.update(is_public=True, audience=[0]), "public event has no audience"),
        (lambda e: e.update(is_public=False), "must name its audience"),
    ],
)
def test_forged_event_markers_are_rejected(mutate, message: str) -> None:
    payload = dump_match_transcript(_play(SEED))
    mutate(payload["turns"][0]["events"][0])
    with pytest.raises(ValueError, match=message):
        validate_match_transcript(build_coin_game_definition(), payload)


def test_event_markers_in_an_old_transcript_are_rejected() -> None:
    payload = dump_match_transcript(_play(SEED))
    payload["schema_version"] = 2
    payload["turns"][0]["events"][0].update(is_public=True)
    with pytest.raises(ValueError, match="predate schema_version 3"):
        validate_match_transcript(build_coin_game_definition(), payload)
