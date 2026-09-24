"""Terminal rendering and input parsing for Liar's Dice.

The renderer receives whichever view the screen was built for: a seat's view
(``my_dice``), the public view (no hands), or, in the replay viewer without
``--seat``, the full state (``dice``: both hands). It shows exactly what it is
given; choosing the right view is the caller's job (see ``arena.cli.play``).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena.cli.games._registry import CliGameAdapter, register_cli_adapter
from arena.games.liarsdice.actions import Bid, Call, LiarsDiceAction
from arena.games.liarsdice.config import LiarsDiceConfig
from arena.games.liarsdice.definition import LIARSDICE_GAME_ID

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
GREEN = "\x1b[32m"


def _faces(dice: list[int]) -> str:
    return " ".join(str(d) for d in dice) if dice else "-"


def _lines(state: Mapping[str, Any]) -> list[str]:
    counts: list[int] = state["dice_counts"]
    lines = [f"  Round {state['round_number']}  (dice in play: {sum(counts)})"]
    for seat, count in enumerate(counts):
        marker = ">" if seat == state["current_seat"] else " "
        lines.append(f"  {marker} Seat {seat}: {count} dice")
    if "my_dice" in state:
        lines.append(f"  Your dice (seat {state['seat']}): {_faces(state['my_dice'])}")
    if state.get("dice") is not None:
        for seat, hand in enumerate(state["dice"]):
            lines.append(f"  Seat {seat} hand: {_faces(hand)}")
    bids = state.get("bids") or []
    history = ", ".join(f"{b['quantity']}x{b['face']}" for b in bids) or "none yet"
    lines.append(f"  Bids this round: {history}")
    showdown = state.get("last_showdown")
    if showdown:
        bid = showdown["bid"]
        lines.append(
            f"  Last call: seat {showdown['caller']} called {bid['quantity']}x{bid['face']}; "
            f"hands {showdown['dice'][0]} / {showdown['dice'][1]} had "
            f"{showdown['count']}; seat {showdown['loser']} lost a die"
        )
    return lines


def render_state(state_payload: Mapping[str, Any]) -> str:
    return "\n".join([f"{BOLD}Liar's Dice{RESET}", *_lines(state_payload)])


def render_state_plain(state_payload: Mapping[str, Any]) -> str:
    return "\n".join(["Liar's Dice", *_lines(state_payload)])


def _parse(text: str) -> LiarsDiceAction | None:
    tokens = text.strip().lower().replace("x", " ").replace("×", " ").split()
    if not tokens:
        return None
    if tokens[0] in ("call", "c", "liar") and len(tokens) == 1:
        return Call()
    if tokens[0] in ("bid", "b"):
        tokens = tokens[1:]
    if len(tokens) != 2:
        return None
    try:
        return Bid(quantity=int(tokens[0]), face=int(tokens[1]))
    except ValueError:
        return None


def parse_input(line: str, observation: Any) -> LiarsDiceAction | None:
    """Parse "bid Q F" (or "Q F", "QxF") or "call" into a legal action, else None."""

    action = _parse(line)
    return action if action is not None and action in observation.legal_actions else None


def _parse_scripted(spec: str) -> list[LiarsDiceAction]:
    actions: list[LiarsDiceAction] = []
    for token in spec.split(","):
        if not token.strip():
            continue
        action = _parse(token)
        if action is None:
            raise ValueError(
                f"Liar's Dice scripted action {token.strip()!r} must be 'bid Q F' or 'call'."
            )
        actions.append(action)
    return actions


def _config_from_args(args: Any) -> LiarsDiceConfig:
    return LiarsDiceConfig(dice_per_seat=args.liarsdice_dice, faces=args.liarsdice_faces)


register_cli_adapter(
    CliGameAdapter(
        game_id=LIARSDICE_GAME_ID,
        renderer=render_state,
        plain_renderer=render_state_plain,
        human_parser=parse_input,
        scripted_parser=_parse_scripted,
        config_factory=_config_from_args,
    )
)


__all__: tuple[str, ...] = ("parse_input", "render_state", "render_state_plain")
