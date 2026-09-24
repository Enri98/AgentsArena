"""Round trips and per-viewer views for the Liar's Dice serializer."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.core.public_view import (
    dump_chance_outcome_for_viewer,
    dump_public_state,
    dump_state_for_seat,
)
from arena.games.liarsdice import (
    Bid,
    Call,
    LiarsDiceConfig,
    LiarsDiceRulesEngine,
    LiarsDiceSerializer,
    LiarsDiceState,
    Roll,
    Showdown,
)

S = LiarsDiceSerializer()
STATE = LiarsDiceState(
    dice=((2, 3, 5), (5, 5, 1)),
    dice_counts=(3, 3),
    bids=(Bid(quantity=2, face=5),),
    current_seat=1,
    round_number=2,
    faces=6,
    last_showdown=Showdown(
        caller=0, bid=Bid(quantity=4, face=2), dice=((2, 2, 1, 4), (6, 3, 3)), count=2, loser=1
    ),
)


def test_state_config_action_round_trips() -> None:
    assert S.load_state(S.dump_state(STATE)) == STATE
    config = LiarsDiceConfig(dice_per_seat=4, faces=8)
    assert S.load_config(S.dump_config(config)) == config
    for action in (Bid(quantity=3, face=2), Call()):
        assert S.load_action(S.dump_action(action)) == action
    assert S.dump_action(Call()) == {"type": "call"}
    assert S.dump_action(Bid(quantity=3, face=2)) == {"type": "bid", "quantity": 3, "face": 2}


@pytest.mark.parametrize(
    "payload",
    [{"type": "raise"}, {"type": "bid", "quantity": 2}, {"type": "call", "face": 1}, {}],
)
def test_malformed_actions_are_rejected(payload: dict) -> None:
    with pytest.raises(ValidationError):
        S.load_action(payload)


def test_observation_round_trip() -> None:
    obs = LiarsDiceRulesEngine().observation(STATE, 1)
    assert S.load_observation(S.dump_observation(obs)) == obs


def test_seat_views_hold_only_the_seats_own_hand() -> None:
    zero = dump_state_for_seat(S, STATE, 0)
    one = dump_state_for_seat(S, STATE, 1)
    assert zero["my_dice"] == [2, 3, 5] and one["my_dice"] == [5, 5, 1]
    for view in (zero, one, dump_public_state(S, STATE)):
        assert "dice" not in view
    # The previous showdown was public; it stays visible to everyone.
    assert dump_public_state(S, STATE)["last_showdown"]["dice"] == [[2, 2, 1, 4], [6, 3, 3]]


def test_a_roll_is_redacted_per_viewer() -> None:
    roll = Roll(dice=((1, 2, 3), (4, 5, 6)))
    assert dump_chance_outcome_for_viewer(S, roll, 0) == {"my_dice": [1, 2, 3]}
    assert dump_chance_outcome_for_viewer(S, roll, 1) == {"my_dice": [4, 5, 6]}
    assert dump_chance_outcome_for_viewer(S, roll, None) == {"dice_counts": [3, 3]}
    assert S.load_chance_outcome(S.dump_chance_outcome(roll)) == roll
