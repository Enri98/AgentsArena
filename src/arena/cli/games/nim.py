"""Terminal renderer for Nim pile state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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


__all__: tuple[str, ...] = ("render_state", "render_state_plain")
