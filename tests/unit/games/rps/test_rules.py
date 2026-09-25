"""Rock-Paper-Scissors: the Phase 41 exemplar simultaneous game."""

from __future__ import annotations

import itertools

import pytest

from arena.core.exceptions import GameFinished, IllegalAction, WrongPlayer
from arena.core.results import Draw, Win
from arena.core.simultaneous import acting_seats, apply_joint_action, is_joint_node
from arena.games.rps import (
    RoundPlayed,
    RoundResult,
    RpsConfig,
    RpsMatchDecided,
    RpsRulesEngine,
    RpsState,
    Throw,
)
from arena.games.rps.state import round_winner

ENGINE = RpsRulesEngine()
ROCK, PAPER, SCISSORS = Throw("rock"), Throw("paper"), Throw("scissors")


def _state(**kw):  # type: ignore[no-untyped-def]
    base = dict(wins=(0, 0), rounds_played=0, target_wins=3, max_rounds=20, last_round=None)
    base.update(kw)
    return RpsState(**base)


@pytest.mark.parametrize(
    ("a", "b", "winner"),
    [
        ("rock", "scissors", 0),
        ("scissors", "paper", 0),
        ("paper", "rock", 0),
        ("scissors", "rock", 1),
        ("paper", "scissors", 1),
        ("rock", "paper", 1),
        ("rock", "rock", None),
        ("paper", "paper", None),
        ("scissors", "scissors", None),
    ],
)
def test_round_winner_follows_the_cycle(a: str, b: str, winner: int | None) -> None:
    assert round_winner((a, b)) == winner


def test_every_live_state_is_a_joint_node_for_both_seats() -> None:
    state = ENGINE.initial_state(RpsConfig())
    assert acting_seats(ENGINE, state) == (0, 1)
    assert is_joint_node(ENGINE, state)
    assert ENGINE.legal_actions(state, 0) == ENGINE.legal_actions(state, 1)
    assert len(ENGINE.legal_actions(state, 0)) == 3


def test_a_round_is_resolved_from_both_throws() -> None:
    state = ENGINE.initial_state(RpsConfig())
    result = apply_joint_action(ENGINE, state, {0: ROCK, 1: SCISSORS})
    assert result.state.wins == (1, 0)
    assert result.state.rounds_played == 1
    assert result.state.last_round == RoundResult(throws=("rock", "scissors"), winner=0)
    assert result.events == (RoundPlayed(round_number=1, throws=["rock", "scissors"], winner=0),)
    assert result.result is None


def test_a_tie_scores_nobody() -> None:
    state = ENGINE.initial_state(RpsConfig())
    result = apply_joint_action(ENGINE, state, {0: PAPER, 1: PAPER})
    assert result.state.wins == (0, 0)
    assert result.state.last_round.winner is None


def test_reaching_target_wins_ends_the_match() -> None:
    state = _state(wins=(2, 1), rounds_played=3, last_round=RoundResult(("rock", "rock"), None))
    result = apply_joint_action(ENGINE, state, {0: PAPER, 1: ROCK})
    assert ENGINE.is_terminal(result.state)
    assert result.result == Win(seat=0)
    assert result.events[-1] == RpsMatchDecided(winner=0)
    assert acting_seats(ENGINE, result.state) == ()
    assert ENGINE.current_seat(result.state) == 0


def test_max_rounds_decides_on_wins_or_draws() -> None:
    last = RoundResult(("rock", "rock"), None)
    state = _state(wins=(1, 1), rounds_played=4, max_rounds=5, last_round=last)
    assert apply_joint_action(ENGINE, state, {0: ROCK, 1: ROCK}).result == Draw()
    assert apply_joint_action(ENGINE, state, {0: SCISSORS, 1: PAPER}).result == Win(seat=0)


def test_a_seat_never_acts_alone() -> None:
    state = ENGINE.initial_state(RpsConfig())
    with pytest.raises(WrongPlayer):
        ENGINE.apply_action(state, 0, ROCK)


@pytest.mark.parametrize("actions", [{0: ROCK}, {1: ROCK}, {0: ROCK, 1: ROCK, 2: ROCK}])
def test_a_round_needs_exactly_both_seats(actions: dict) -> None:
    with pytest.raises(WrongPlayer):
        apply_joint_action(ENGINE, ENGINE.initial_state(RpsConfig()), actions)


def test_a_throw_must_be_a_throw() -> None:
    from arena.games.pig import PigMove

    with pytest.raises(IllegalAction):
        ENGINE.validate_action(ENGINE.initial_state(RpsConfig()), 0, PigMove(choice="roll"))


def test_nothing_is_legal_once_the_match_is_over() -> None:
    state = _state(wins=(3, 0), rounds_played=3, last_round=RoundResult(("rock", "scissors"), 0))
    assert ENGINE.legal_actions(state, 0) == ()
    with pytest.raises(GameFinished):
        ENGINE.validate_action(state, 0, ROCK)


def test_the_observation_shows_the_score_not_a_pending_throw() -> None:
    state = _state(wins=(1, 0), rounds_played=2, last_round=RoundResult(("rock", "rock"), None))
    obs = ENGINE.observation(state, 1)
    assert (obs.seat, obs.wins, obs.rounds_played) == (1, (1, 0), 2)
    assert obs.last_round == state.last_round


@pytest.mark.parametrize(
    "kw",
    [
        {"wins": (4, 0), "rounds_played": 4},  # past target_wins
        {"wins": (3, 3), "rounds_played": 6},  # both at target
        {"wins": (2, 2), "rounds_played": 3},  # more wins than rounds
        {"rounds_played": 21},  # past max_rounds
        {"rounds_played": 1},  # a round played but no last_round
        {"target_wins": 11},
        {"max_rounds": 101},
    ],
)
def test_unreachable_states_are_refused(kw: dict) -> None:
    with pytest.raises(ValueError):
        _state(**kw)


def test_a_round_result_must_match_its_throws() -> None:
    with pytest.raises(ValueError):
        RoundResult(throws=("rock", "paper"), winner=0)


def test_every_throw_pair_resolves() -> None:
    state = ENGINE.initial_state(RpsConfig())
    for a, b in itertools.product(ENGINE.legal_actions(state, 0), repeat=2):
        result = apply_joint_action(ENGINE, state, {0: a, 1: b})
        assert sum(result.state.wins) == (0 if a == b else 1)


@pytest.mark.parametrize(
    "kw",
    [
        {"wins": (0, 0), "rounds_played": 1, "last_round": RoundResult(("rock", "scissors"), 0)},
        {"wins": (3, 0), "rounds_played": 4, "last_round": RoundResult(("rock", "rock"), None)},
        {"wins": (3, 1), "rounds_played": 4, "last_round": RoundResult(("rock", "paper"), 1)},
    ],
)
def test_states_that_cannot_follow_from_play_are_refused(kw: dict) -> None:
    with pytest.raises(ValueError):
        _state(**kw)


def test_every_reachable_state_is_accepted_over_many_matches() -> None:
    import random

    from arena.games import build_default_registry
    from arena.match import run_local_match, start_match

    rps = build_default_registry().get("rps")

    class Rand:
        def __init__(self, seed: int) -> None:
            self.r = random.Random(seed)

        def select_action(self, obs):  # type: ignore[no-untyped-def]
            return self.r.choice(obs.legal_actions)

    for seed in range(300):
        config = RpsConfig(target_wins=1 + seed % 10, max_rounds=1 + (seed * 7) % 100)
        match = run_local_match(start_match(rps, config), {0: Rand(seed), 1: Rand(-seed)})
        for turn in match.turns:
            state = turn.post_state
            assert RpsState(**{f: getattr(state, f) for f in state.__dataclass_fields__}) == state
