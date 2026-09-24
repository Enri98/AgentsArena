"""Liar's Dice in the CLI: parsing, rendering, and per-seat live screens."""

from __future__ import annotations

import argparse
import io
import json
import re

import pytest

from arena.cli.games import get_cli_adapter
from arena.cli.games.liarsdice import parse_input, render_state_plain
from arena.cli.play import play_match
from arena.cli.policies import HumanPolicy
from arena.games.liarsdice import (
    Bid,
    Call,
    LiarsDiceConfig,
    LiarsDiceGameDefinition,
    LiarsDiceRulesEngine,
    LiarsDiceState,
)
from arena.mcp.schemas import LIARSDICE_ACTION_SCHEMA, game_action_schema
from arena.runtime import PlayerRecord

ENGINE = LiarsDiceRulesEngine()
STATE = LiarsDiceState(
    dice=((2, 3, 5), (5, 5, 1)),
    dice_counts=(3, 3),
    bids=(Bid(quantity=2, face=4),),
    current_seat=1,
    round_number=1,
    faces=6,
)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("bid 3 5", Bid(quantity=3, face=5)),
        ("b 2 6", Bid(quantity=2, face=6)),
        ("3 1", Bid(quantity=3, face=1)),
        ("3x5", Bid(quantity=3, face=5)),
        ("call", Call()),
        ("liar", Call()),
    ],
)
def test_human_input(line: str, expected: object) -> None:
    assert parse_input(line, ENGINE.observation(STATE, 1)) == expected


@pytest.mark.parametrize("line", ["bid 2 3", "bid 7 6", "call now", "", "raise 3 3"])
def test_illegal_or_garbled_input_is_refused(line: str) -> None:
    assert parse_input(line, ENGINE.observation(STATE, 1)) is None


def test_scripted_parser_and_config_factory() -> None:
    adapter = get_cli_adapter("liarsdice")
    assert adapter.scripted_parser("bid 1 2, call") == [Bid(quantity=1, face=2), Call()]
    with pytest.raises(ValueError):
        adapter.scripted_parser("bid 1")
    args = argparse.Namespace(liarsdice_dice=2, liarsdice_faces=4)
    assert adapter.config_factory(args) == LiarsDiceConfig(dice_per_seat=2, faces=4)


def test_rendering_shows_exactly_the_view_it_is_given() -> None:
    serializer = LiarsDiceGameDefinition.serializer
    seat_view = render_state_plain(serializer.dump_state_for_seat(STATE, 0))
    assert "Your dice (seat 0): 2 3 5" in seat_view
    assert "hand" not in seat_view and "5 5 1" not in seat_view

    public_view = render_state_plain(serializer.dump_public_state(STATE))
    assert "Your dice" not in public_view and "2 3 5" not in public_view
    assert "Bids this round: 2x4" in public_view
    assert all(ord(ch) < 128 for ch in public_view)  # Windows consoles are cp1252


def test_mcp_schema_is_registered() -> None:
    assert game_action_schema("liarsdice") is LIARSDICE_ACTION_SCHEMA
    kinds = [option["properties"]["type"]["const"] for option in LIARSDICE_ACTION_SCHEMA["oneOf"]]
    assert kinds == ["bid", "call"]


def test_the_live_screen_shows_only_the_human_seats_hand(tmp_path) -> None:
    """Seat 0 is human; until the first call, its screen never shows seat 1's hand."""

    definition = LiarsDiceGameDefinition
    from arena.adapters.in_process import TypedPayloadPolicyAdapter
    from arena.cli.play.__main__ import _ScriptedPolicy

    out = io.StringIO()
    human = HumanPolicy(
        parse_input, stdin=io.StringIO("bid 1 1\ncall\n" * 6), stdout=out
    )
    opponent = _ScriptedPolicy([Bid(quantity=6, face=6)] * 6, seat_index=1)
    code = play_match(
        definition,
        LiarsDiceConfig(),
        (PlayerRecord(player_id="h", seat=0), PlayerRecord(player_id="s", seat=1)),
        {
            0: TypedPayloadPolicyAdapter(definition, human),
            1: TypedPayloadPolicyAdapter(definition, opponent),
        },
        human_seats=(0,),
        out_dir=tmp_path,
        stdout=out,
    )
    assert code in (0, 1)
    screen = re.sub(r"\x1b\[[0-9;]*m", "", out.getvalue())
    before_first_call = screen.split("Last call:")[0]

    transcript = json.loads((tmp_path / "transcript.json").read_text("utf-8"))
    first_roll = transcript["match_transcript"]["turns"][0]["outcome"]["dice"]
    assert "Your dice (seat 0): " + " ".join(map(str, first_roll[0])) in before_first_call
    assert "Seat 1 hand" not in screen and "Your dice (seat 1)" not in screen
    assert '"my_dice": ' + json.dumps(first_roll[1]) not in before_first_call
    assert "Seat 0's view" in screen
