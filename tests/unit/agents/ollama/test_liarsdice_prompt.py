"""Tests for LiarsDicePromptBuilder."""

from __future__ import annotations

from arena.agents.ollama._adapters import get_ollama_adapter
from arena.agents.ollama.liarsdice import LiarsDicePromptBuilder
from arena.games.liarsdice import Bid, Call, LiarsDiceRulesEngine, LiarsDiceState

ENGINE = LiarsDiceRulesEngine()
BUILDER = LiarsDicePromptBuilder()


def _obs(bids: tuple[Bid, ...] = (), seat: int = 1):
    state = LiarsDiceState(
        dice=((2, 3, 5), (5, 5, 1)),
        dice_counts=(3, 3),
        bids=bids,
        current_seat=seat,
        round_number=1,
        faces=6,
    )
    return ENGINE.observation(state, seat)


def test_the_prompt_shows_the_seats_own_hand_only() -> None:
    user = BUILDER.build_messages(_obs(bids=(Bid(quantity=2, face=5),)))[-1]["content"]
    assert "Your dice: [1, 5, 5]" in user
    assert "Opponent has 3 hidden dice" in user
    assert "2, 3" not in user  # nothing of seat 0's hand
    assert "You hold 2 of them" in user
    assert '"call"' in user


def test_an_opening_prompt_offers_no_call() -> None:
    user = BUILDER.build_messages(_obs(seat=0))[-1]["content"]
    assert "must open with a bid" in user
    assert '"call"' not in user


def test_parses_legal_moves_only() -> None:
    obs = _obs(bids=(Bid(quantity=2, face=5),))
    assert BUILDER.parse_response('{"action": "call"}', obs) == Call()
    assert BUILDER.parse_response(
        '{"thought": "x", "action": "bid", "quantity": 3, "face": 5}', obs
    ) == Bid(quantity=3, face=5)
    for bad in (
        '{"action": "bid", "quantity": 2, "face": 4}',  # does not raise the bid
        '{"action": "bid", "quantity": "3", "face": 5}',
        '{"action": "bid", "quantity": true, "face": 5}',
        '{"action": "fold"}',
        "not json",
        "[]",
    ):
        assert BUILDER.parse_response(bad, obs) is None, bad
    assert BUILDER.parse_response('{"action": "call"}', _obs(seat=0)) is None


def test_format_spec_and_registration() -> None:
    spec = BUILDER.format_spec()
    assert spec["properties"]["action"]["enum"] == ["bid", "call"]
    assert get_ollama_adapter("liarsdice").prompt_builder_factory is LiarsDicePromptBuilder
