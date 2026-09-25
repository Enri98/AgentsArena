"""Terminal renderer and input parsing for Rock-Paper-Scissors."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena.cli.games._registry import CliGameAdapter, register_cli_adapter
from arena.games.rps.actions import SHAPES, Throw
from arena.games.rps.config import RpsConfig
from arena.games.rps.definition import RPS_GAME_ID

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
GREEN = "\x1b[32m"

#: Single-letter shortcuts accepted alongside the full words.
_ALIASES = {"r": "rock", "p": "paper", "s": "scissors"}


def _lines(state_payload: Mapping[str, Any]) -> list[str]:
    wins: list[int] = state_payload["wins"]
    lines = [
        f"  First to {state_payload['target_wins']} wins "
        f"(round {state_payload['rounds_played']} of at most {state_payload['max_rounds']})"
    ]
    for seat, won in enumerate(wins):
        lines.append(f"    Seat {seat}: {won}")
    last = state_payload.get("last_round")
    if last is not None:
        throws = last["throws"]
        outcome = "tie" if last["winner"] is None else f"seat {last['winner']} wins it"
        lines.append(f"  Last round: {throws[0]} vs {throws[1]} ({outcome})")
    return lines


def render_state(state_payload: Mapping[str, Any]) -> str:
    """Render the score and the last round."""
    return "\n".join([f"{BOLD}Rock-Paper-Scissors{RESET}", *_lines(state_payload)])


def render_state_plain(state_payload: Mapping[str, Any]) -> str:
    """Plain-text state (no ANSI)."""
    return "\n".join(["Rock-Paper-Scissors", *_lines(state_payload)])


def _normalise(token: str) -> str | None:
    word = token.strip().lower()
    word = _ALIASES.get(word, word)
    return word if word in SHAPES else None


def parse_input(line: str, observation: Any) -> Throw | None:
    """Parse "rock"/"paper"/"scissors" (or "r"/"p"/"s") into a legal Throw."""
    shape = _normalise(line)
    if shape is None:
        return None
    action = Throw(shape=shape)
    return action if action in observation.legal_actions else None


def _parse_scripted(spec: str) -> list[Throw]:
    actions: list[Throw] = []
    for token in spec.split(","):
        if not token.strip():
            continue
        shape = _normalise(token)
        if shape is None:
            raise ValueError(
                f"RPS scripted throw {token.strip()!r} must be rock, paper or scissors."
            )
        actions.append(Throw(shape=shape))
    return actions


def _config_from_args(args: Any) -> RpsConfig:
    return RpsConfig(target_wins=args.rps_target, max_rounds=args.rps_max_rounds)


register_cli_adapter(
    CliGameAdapter(
        game_id=RPS_GAME_ID,
        renderer=render_state,
        plain_renderer=render_state_plain,
        human_parser=parse_input,
        scripted_parser=_parse_scripted,
        config_factory=_config_from_args,
    )
)


__all__: tuple[str, ...] = ("parse_input", "render_state", "render_state_plain")
