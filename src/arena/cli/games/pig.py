"""Terminal renderer and input parsing for Pig."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena.cli.games._registry import CliGameAdapter, register_cli_adapter
from arena.games.pig.actions import HOLD, PIG_CHOICES, ROLL, PigMove
from arena.games.pig.config import PigConfig
from arena.games.pig.definition import PIG_GAME_ID

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
GREEN = "\x1b[32m"

#: Single-letter shortcuts accepted alongside the full words.
_ALIASES = {"r": ROLL, "h": HOLD}


def _lines(state_payload: Mapping[str, Any]) -> list[str]:
    scores: list[int] = state_payload["scores"]
    target = state_payload["target_score"]
    current = state_payload["current_seat"]
    lines = [f"  Target: {target}"]
    for seat, score in enumerate(scores):
        marker = ">" if seat == current else " "
        lines.append(f"  {marker} Seat {seat}: {score}")
    lines.append(f"  Turn total: {state_payload['turn_total']}")
    return lines


def render_state(state_payload: Mapping[str, Any]) -> str:
    """Render Pig scores and the running turn total."""
    body = _lines(state_payload)
    body[-1] = f"  Turn total: {GREEN}{state_payload['turn_total']}{RESET}"
    return "\n".join([f"{BOLD}Pig{RESET}", *body])


def render_state_plain(state_payload: Mapping[str, Any]) -> str:
    """Plain-text Pig state (no ANSI)."""
    return "\n".join(["Pig", *_lines(state_payload)])


def _normalise(token: str) -> str | None:
    word = token.strip().lower()
    word = _ALIASES.get(word, word)
    return word if word in PIG_CHOICES else None


def parse_input(line: str, observation: Any) -> PigMove | None:
    """Parse "roll"/"hold" (or "r"/"h") and return a legal PigMove or None."""
    choice = _normalise(line)
    if choice is None:
        return None
    action = PigMove(choice=choice)
    return action if action in observation.legal_actions else None


def _parse_scripted(spec: str) -> list[PigMove]:
    actions: list[PigMove] = []
    for token in spec.split(","):
        if not token.strip():
            continue
        choice = _normalise(token)
        if choice is None:
            raise ValueError(f"Pig scripted action {token.strip()!r} must be 'roll' or 'hold'.")
        actions.append(PigMove(choice=choice))
    return actions


def _config_from_args(args: Any) -> PigConfig:
    return PigConfig(target_score=args.pig_target)


register_cli_adapter(
    CliGameAdapter(
        game_id=PIG_GAME_ID,
        renderer=render_state,
        plain_renderer=render_state_plain,
        human_parser=parse_input,
        scripted_parser=_parse_scripted,
        config_factory=_config_from_args,
    )
)


__all__: tuple[str, ...] = ("parse_input", "render_state", "render_state_plain")
