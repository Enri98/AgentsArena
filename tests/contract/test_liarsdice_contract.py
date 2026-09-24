"""The shared contract for Liar's Dice: hidden information plus chance.

The private variants swap one seat's hand while keeping everything the other
seat may see, on both seats' turns and with and without a standing bid. "Call"
is declared as revealing: showing both hands is its whole point.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from arena.core.results import Win
from arena.games.liarsdice import (
    LIARSDICE_GAME_ID,
    Bid,
    Call,
    LiarsDiceConfig,
    LiarsDiceGameDefinition,
    LiarsDiceState,
    Roll,
)
from arena.testing import PrivateVariant, assert_game_contract


@dataclass(frozen=True)
class LiarsDiceContractBundle:
    definition: object
    config: LiarsDiceConfig
    initial_state: LiarsDiceState
    near_terminal_state: LiarsDiceState
    terminal_state: LiarsDiceState
    legal_action: object
    illegal_action: object
    terminal_action: object
    opening_outcomes: tuple[Roll, ...]
    private_variants: tuple[PrivateVariant, ...]
    chance_state: LiarsDiceState
    private_outcome_variants: tuple[PrivateVariant, ...]
    revealing_actions: tuple[object, ...]


def build_liarsdice_contract_bundle() -> LiarsDiceContractBundle:
    definition = LiarsDiceGameDefinition
    engine = definition.rules_engine
    config = LiarsDiceConfig()
    opening_roll = Roll(dice=((2, 3, 5), (5, 5, 1)))
    opening = engine.apply_chance(engine.initial_state(config), opening_roll).state

    bid_standing = replace(opening, bids=(Bid(quantity=2, face=5),), current_seat=1)
    near_terminal = LiarsDiceState(
        dice=((6,), (5, 5)),
        dice_counts=(1, 2),
        bids=(Bid(quantity=3, face=5),),
        current_seat=1,
        round_number=3,
        faces=6,
    )

    def swap(state: LiarsDiceState, seat: int, hand: tuple[int, ...]) -> LiarsDiceState:
        dice = list(state.dice)
        dice[seat] = hand
        return replace(state, dice=(dice[0], dice[1]))

    variants = []
    for state in (opening, bid_standing):
        variants.append(PrivateVariant(state, swap(state, 1, (6, 6, 6)), blind_seat=0))
        variants.append(PrivateVariant(state, swap(state, 0, (1, 1, 4)), blind_seat=1))
    variants.append(PrivateVariant(near_terminal, swap(near_terminal, 0, (2,)), blind_seat=1))

    return LiarsDiceContractBundle(
        definition=definition,
        config=config,
        initial_state=opening,
        near_terminal_state=near_terminal,
        terminal_state=engine.apply_action(near_terminal, 1, Call()).state,
        legal_action=Bid(quantity=1, face=1),
        illegal_action=Call(),  # nothing to call at the opening
        terminal_action=Call(),
        opening_outcomes=(opening_roll,),
        private_variants=tuple(variants),
        chance_state=engine.initial_state(config),
        private_outcome_variants=(
            PrivateVariant(opening_roll, Roll(dice=((2, 3, 5), (6, 6, 6))), blind_seat=0),
            PrivateVariant(opening_roll, Roll(dice=((1, 1, 4), (5, 5, 1))), blind_seat=1),
        ),
        revealing_actions=(Call(),),
    )


def test_liarsdice_passes_the_shared_contract() -> None:
    bundle = build_liarsdice_contract_bundle()
    assert bundle.definition.game_id == LIARSDICE_GAME_ID
    assert bundle.definition.has_hidden_information and bundle.definition.has_chance_nodes
    assert_game_contract(bundle)


def test_near_terminal_call_ends_it_for_the_caller() -> None:
    bundle = build_liarsdice_contract_bundle()
    engine = bundle.definition.rules_engine
    assert engine.result(bundle.terminal_state) == Win(seat=1)
