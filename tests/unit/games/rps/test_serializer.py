"""Rock-Paper-Scissors serializer round trips."""

from __future__ import annotations

import json
import random

import pytest
from pydantic import ValidationError

from arena.games import build_default_registry
from arena.match import run_local_match, start_match

DEF = build_default_registry().get("rps")


class _Random:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def select_action(self, observation):  # type: ignore[no-untyped-def]
        return self.rng.choice(observation.legal_actions)


def test_every_reachable_state_observation_and_action_round_trips() -> None:
    s = DEF.serializer
    for seed in range(40):
        config = DEF.config_type(target_wins=1 + seed % 5, max_rounds=1 + seed % 12)
        match = run_local_match(
            start_match(DEF, config), {0: _Random(seed), 1: _Random(seed + 99)}
        )
        assert s.load_config(json.loads(json.dumps(s.dump_config(config)))) == config
        for turn in match.turns:
            dumped = json.loads(json.dumps(s.dump_state(turn.post_state)))
            assert s.load_state(dumped) == turn.post_state
            for seat, action in turn.actions.items():
                assert s.load_action(s.dump_action(action)) == action
                obs = DEF.rules_engine.observation(turn.post_state, seat)
                assert s.load_observation(json.loads(json.dumps(s.dump_observation(obs)))) == obs


@pytest.mark.parametrize("payload", [{"shape": "lizard"}, {"shape": "ROCK"}, {}])
def test_an_unknown_throw_does_not_load(payload: dict) -> None:
    with pytest.raises((ValidationError, ValueError)):
        DEF.serializer.load_action(payload)


@pytest.mark.parametrize(
    "config", [{"target_wins": 0}, {"target_wins": 11}, {"max_rounds": 0}, {"max_rounds": 101}]
)
def test_config_is_bounded(config: dict) -> None:
    with pytest.raises((ValidationError, ValueError)):
        DEF.serializer.load_config(config)
