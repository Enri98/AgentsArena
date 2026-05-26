"""Terminal renderer for Nim pile state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from arena.cli.games._registry import CliGameAdapter, register_cli_adapter
from arena.games.nim.actions import TakeObjects
from arena.games.nim.config import NimConfig
from arena.games.nim.definition import NIM_GAME_ID

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
GREEN = "\x1b[32m"

_MAX_BAR_WIDTH = 20


def render_state(state_payload: Mapping[str, Any]) -> str:
    """Render the Nim pile state as a bar chart."""
    piles: list[int] = state_payload["piles"]
    max_size = max(piles) if piles else 1
    lines: list[str] = [f"{BOLD}Nim — piles:{RESET}"]
    for i, size in enumerate(piles):
        bar_width = int(size / max(max_size, 1) * _MAX_BAR_WIDTH) if max_size > 0 else 0
        bar = f"{GREEN}{'|' * bar_width}{RESET}"
        if size == 0:
            bar = f"{DIM}(empty){RESET}"
        lines.append(f"  Pile {i}: {bar}  {size}")
    return "\n".join(lines)


def render_state_plain(state_payload: Mapping[str, Any]) -> str:
    """Plain-text Nim pile state (no ANSI)."""
    piles: list[int] = state_payload["piles"]
    lines: list[str] = ["Nim piles:"]
    for i, size in enumerate(piles):
        bar = "|" * size if size > 0 else "(empty)"
        lines.append(f"  Pile {i}: {bar}  {size}")
    return "\n".join(lines)


def parse_input(line: str, observation: Any) -> TakeObjects | None:
    """Parse "<pile> <count>" from *line* and return a legal TakeObjects or None."""
    stripped = line.strip()
    if not stripped:
        return None
    parts = stripped.split()
    if len(parts) != 2:
        return None
    try:
        pile_index = int(parts[0])
        count = int(parts[1])
    except ValueError:
        return None
    try:
        action = TakeObjects(pile_index=pile_index, count=count)
    except ValueError:
        return None
    if action in observation.legal_actions:
        return action
    return None


def _parse_scripted(spec: str) -> list[TakeObjects]:
    actions: list[TakeObjects] = []
    for v in spec.split(","):
        v = v.strip()
        if not v:
            continue
        parts = v.split()
        if len(parts) != 2:
            raise ValueError(
                f"Nim scripted action {v!r} must be '<pile> <count>'."
            )
        actions.append(TakeObjects(pile_index=int(parts[0]), count=int(parts[1])))
    return actions


def _config_from_args(args: Any) -> NimConfig:
    return NimConfig(num_piles=args.nim_piles, max_pile_size=args.nim_pile_size)


register_cli_adapter(
    CliGameAdapter(
        game_id=NIM_GAME_ID,
        renderer=render_state,
        plain_renderer=render_state_plain,
        human_parser=parse_input,
        scripted_parser=_parse_scripted,
        config_factory=_config_from_args,
    )
)


__all__: tuple[str, ...] = ("parse_input", "render_state", "render_state_plain")
