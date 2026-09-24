"""Tests for the Liar's Dice rules engine."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.core.chance import ChanceRng
from arena.core.exceptions import ChanceResolutionError, GameFinished, IllegalAction, WrongPlayer
from arena.core.results import Win
from arena.games.liarsdice import (
    Bid,
    BidCalled,
    BidMade,
    Call,
    DiceDealt,
    DieLost,
    LiarsDiceConfig,
    LiarsDiceMatchWon,
    LiarsDiceRulesEngine,
    LiarsDiceState,
    Roll,
    RoundRolled,
)

ENGINE = LiarsDiceRulesEngine()


def _state(**overrides: object) -> LiarsDiceState:
    fields: dict = dict(
        dice=((2, 3, 5), (5, 5, 1)),
        dice_counts=(3, 3),
        bids=(),
        current_seat=0,
        round_number=1,
        faces=6,
    )
    fields.update(overrides)
    return LiarsDiceState(**fields)


def test_config_defaults_and_bounds() -> None:
    assert LiarsDiceConfig() == LiarsDiceConfig(dice_per_seat=3, faces=6)
    assert "seed" not in LiarsDiceConfig.model_fields
    with pytest.raises(ValidationError):
        LiarsDiceConfig(dice_per_seat=0)
    with pytest.raises(ValidationError):
        LiarsDiceConfig(faces=1)


def test_the_match_opens_at_a_roll() -> None:
    state = ENGINE.initial_state(LiarsDiceConfig())
    assert state.dice is None and state.round_number == 0
    assert ENGINE.is_chance_node(state)
    assert ENGINE.legal_actions(state, 0) == ()
    with pytest.raises(IllegalAction):
        ENGINE.validate_action(state, 0, Bid(quantity=1, face=1))


def test_rolling_deals_private_hands() -> None:
    state = ENGINE.initial_state(LiarsDiceConfig())
    transition = ENGINE.apply_chance(state, Roll(dice=((1, 2, 3), (4, 5, 6))))

    assert transition.state.dice == ((1, 2, 3), (4, 5, 6))
    assert transition.state.round_number == 1
    events = transition.events
    assert events[0] == RoundRolled(round_number=1, dice_counts=[3, 3])
    assert events[1] == DiceDealt(seat=0, dice=[1, 2, 3])
    assert events[0].is_public
    assert events[1].visible_to(0) and not events[1].visible_to(1)
    assert not events[1].visible_to(None)


@pytest.mark.parametrize(
    "roll",
    [
        Roll(dice=((1, 2), (4, 5, 6))),  # wrong count
        Roll(dice=((1, 2, 7), (4, 5, 6))),  # impossible face
        Roll(dice=((1, 2, 0), (4, 5, 6))),
    ],
)
def test_impossible_rolls_are_rejected(roll: Roll) -> None:
    with pytest.raises(ChanceResolutionError):
        ENGINE.apply_chance(ENGINE.initial_state(LiarsDiceConfig()), roll)


def test_sampled_rolls_match_the_dice_counts() -> None:
    state = _state(dice=None, dice_counts=(2, 3))
    roll, _ = ENGINE.sample_chance(state, ChanceRng(seed=9))
    assert [len(hand) for hand in roll.dice] == [2, 3]
    assert all(1 <= d <= 6 for hand in roll.dice for d in hand)


def test_opening_bids_and_no_call() -> None:
    legal = ENGINE.legal_actions(_state(), 0)
    assert Call() not in legal
    assert len(legal) == 6 * 6  # quantities 1..6 of faces 1..6


def test_bids_must_rise() -> None:
    state = _state(bids=(Bid(quantity=2, face=4),), current_seat=1)
    legal = ENGINE.legal_actions(state, 1)
    assert legal[0] == Call()
    assert Bid(quantity=2, face=5) in legal
    assert Bid(quantity=3, face=1) in legal
    assert Bid(quantity=2, face=4) not in legal and Bid(quantity=1, face=6) not in legal
    with pytest.raises(IllegalAction, match="raise"):
        ENGINE.validate_action(state, 1, Bid(quantity=2, face=3))
    with pytest.raises(IllegalAction):
        ENGINE.validate_action(state, 1, Bid(quantity=7, face=6))  # only 6 dice in play
    with pytest.raises(WrongPlayer):
        ENGINE.validate_action(state, 0, Call())


def test_a_bid_passes_the_turn() -> None:
    transition = ENGINE.apply_action(_state(), 0, Bid(quantity=2, face=5))
    assert transition.state.bids == (Bid(quantity=2, face=5),)
    assert transition.state.current_seat == 1
    assert transition.events == (BidMade(seat=0, quantity=2, face=5),)


def test_calling_a_true_bid_costs_the_caller() -> None:
    # Three fives showing; seat 0 bid three fives, seat 1 calls and is wrong.
    state = _state(bids=(Bid(quantity=3, face=5),), current_seat=1)
    transition = ENGINE.apply_action(state, 1, Call())

    called = transition.events[0]
    assert isinstance(called, BidCalled) and called.is_public
    assert called.dice == [[2, 3, 5], [5, 5, 1]] and called.count == 3 and called.loser == 1
    assert transition.events[1] == DieLost(seat=1, remaining=2)
    nxt = transition.state
    assert nxt.dice_counts == (3, 2)
    assert nxt.dice is None and ENGINE.is_chance_node(nxt)  # a new round rolls
    assert nxt.current_seat == 1  # the loser opens
    assert nxt.last_showdown is not None and nxt.last_showdown.loser == 1


def test_calling_a_false_bid_costs_the_bidder() -> None:
    state = _state(bids=(Bid(quantity=4, face=5),), current_seat=1)
    transition = ENGINE.apply_action(state, 1, Call())
    assert transition.events[0].loser == 0
    assert transition.state.dice_counts == (2, 3)
    assert transition.state.current_seat == 0


def test_losing_the_last_die_ends_the_match() -> None:
    state = _state(
        dice=((6,), (5, 5)),
        dice_counts=(1, 2),
        bids=(Bid(quantity=3, face=5),),
        current_seat=1,
    )
    transition = ENGINE.apply_action(state, 1, Call())  # only two fives: seat 0 bluffed

    assert transition.state.dice_counts == (0, 2)
    assert transition.result == Win(seat=1)
    assert transition.events[-1] == LiarsDiceMatchWon(winner_seat=1)
    assert ENGINE.is_terminal(transition.state)
    assert not ENGINE.is_chance_node(transition.state)
    with pytest.raises(GameFinished):
        ENGINE.apply_action(transition.state, 0, Bid(quantity=1, face=1))


def test_the_observation_shows_only_the_seats_own_hand() -> None:
    obs = ENGINE.observation(_state(), 1)
    assert obs.my_dice == (5, 5, 1)
    assert not hasattr(obs, "dice")
    assert obs.legal_actions == ()  # seat 0 is to move


# -- adversarial review of Slice 1 ------------------------------------------


def test_a_finished_match_has_no_pending_roll_and_the_winner_holds_the_table() -> None:
    from arena.games.liarsdice import LiarsDiceSerializer

    state = _state(dice=((6,), (5, 5)), dice_counts=(1, 2), bids=(Bid(quantity=3, face=5),),
                   current_seat=1)
    final = ENGINE.apply_action(state, 1, Call()).state
    assert ENGINE.is_terminal(final)
    assert final.current_seat == 1  # the winner, not the eliminated seat
    assert ENGINE.public_state(final).roll_pending is False
    serializer = LiarsDiceSerializer()
    assert serializer.dump_public_state(final)["roll_pending"] is False
    assert serializer.dump_state_for_seat(final, 0)["roll_pending"] is False


@pytest.mark.parametrize("seat", [-1, 2, True])
def test_observations_are_only_for_real_seats(seat: object) -> None:
    with pytest.raises(ValueError):
        ENGINE.observation(_state(), seat)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "roll",
    [
        Roll(dice=((1, 2, 3), 5)),  # type: ignore[arg-type]
        Roll(dice=[[1, 2, 3], [4, 5, 6]]),  # type: ignore[arg-type]
        Roll(dice=((1, 2, 3),)),  # type: ignore[arg-type]
    ],
)
def test_malformed_rolls_are_domain_errors(roll: Roll) -> None:
    with pytest.raises(ChanceResolutionError):
        ENGINE.apply_chance(ENGINE.initial_state(LiarsDiceConfig()), roll)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda p: p.update(faces=1000),
        lambda p: p.update(bids=[{"quantity": 99, "face": 2}]),
        lambda p: p.update(bids=[{"quantity": 2, "face": 3}, {"quantity": 1, "face": 6}]),
        lambda p: p.update(round_number=0),
        lambda p: p.update(dice_counts=[-1, 3]),
        lambda p: p.update(
            last_showdown={"caller": 0, "bid": {"quantity": 1, "face": 2},
                           "dice": [[1], [2, 3]], "count": 99, "loser": 1}
        ),
    ],
)
def test_impossible_states_do_not_load(mutate) -> None:
    from pydantic import ValidationError as PydanticValidationError

    from arena.games.liarsdice import LiarsDiceSerializer

    serializer = LiarsDiceSerializer()
    payload = serializer.dump_state(_state())
    mutate(payload)
    with pytest.raises((ValueError, PydanticValidationError)):
        serializer.load_state(payload)
