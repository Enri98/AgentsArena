"""Round-trip tests for the Pig serializer."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.games.pig import (
    HOLD,
    ROLL,
    DieRoll,
    PigConfig,
    PigMove,
    PigRulesEngine,
    PigSerializer,
    PigState,
)

SERIALIZER = PigSerializer()


def test_config_round_trip() -> None:
    config = PigConfig(target_score=75)
    assert SERIALIZER.dump_config(config) == {"target_score": 75}
    assert SERIALIZER.load_config(SERIALIZER.dump_config(config)) == config


def test_state_round_trip() -> None:
    state = PigState(
        scores=(12, 40), current_seat=1, turn_total=9, roll_pending=True, target_score=50
    )
    payload = SERIALIZER.dump_state(state)
    assert payload == {
        "scores": [12, 40],
        "current_seat": 1,
        "turn_total": 9,
        "roll_pending": True,
        "target_score": 50,
    }
    assert SERIALIZER.load_state(payload) == state


@pytest.mark.parametrize("choice", [ROLL, HOLD])
def test_action_round_trip(choice: str) -> None:
    move = PigMove(choice=choice)
    assert SERIALIZER.dump_action(move) == {"choice": choice}
    assert SERIALIZER.load_action({"choice": choice}) == move


def test_unknown_choices_are_rejected_at_the_boundary() -> None:
    with pytest.raises(ValidationError):
        SERIALIZER.load_action({"choice": "pass"})
    with pytest.raises(ValidationError):
        SERIALIZER.load_action({"choice": "roll", "face": 6})


def test_observation_round_trip() -> None:
    engine = PigRulesEngine()
    state = PigState(
        scores=(5, 0), current_seat=0, turn_total=4, roll_pending=False, target_score=20
    )
    obs = engine.observation(state, 0)
    assert SERIALIZER.load_observation(SERIALIZER.dump_observation(obs)) == obs


def test_chance_outcome_round_trip() -> None:
    assert SERIALIZER.dump_chance_outcome(DieRoll(face=4)) == {"face": 4}
    assert SERIALIZER.load_chance_outcome({"face": 4}) == DieRoll(face=4)


@pytest.mark.parametrize("payload", [{"face": 0}, {"face": 7}, {"face": "6"}, {}])
def test_malformed_outcomes_are_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        SERIALIZER.load_chance_outcome(payload)
