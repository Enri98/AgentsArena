"""Pure terminal rendering of UIMatchScreenPayload dicts."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from arena.cli.games import CLI_GAME_ADAPTERS

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
GREEN = "\x1b[32m"
BLUE = "\x1b[34m"
CYAN = "\x1b[36m"

_LIFECYCLE_COLORS: dict[str, str] = {
    "running": GREEN,
    "created": DIM,
    "finished": BLUE,
    "aborted": RED,
}


def render_match_screen(screen_payload: Mapping[str, Any]) -> str:
    status: Mapping[str, Any] = screen_payload["status"]
    transcript: Mapping[str, Any] = screen_payload["transcript"]

    parts: list[str] = []
    parts.append(_render_header(status))

    board_str = _render_board(status)
    if board_str is not None:
        parts.append(board_str)

    parts.append(_render_players(status))
    parts.append(_render_status_line(status))

    lifecycle = status["lifecycle"]
    if lifecycle == "finished":
        parts.append(_render_result(status))
    if lifecycle == "aborted":
        parts.append(_render_abort(status))

    parts.append(_render_runtime_events(transcript))
    parts.append(_render_turn_history(transcript))

    return "\n".join(parts)


def _render_header(status: Mapping[str, Any]) -> str:
    lifecycle = status["lifecycle"]
    color = _LIFECYCLE_COLORS.get(lifecycle, "")
    return (
        f"{BOLD}Match {status['match_id']} — {status['game_id']}{RESET}"
        f"  {color}{lifecycle}{RESET}"
    )


def _render_board(status: Mapping[str, Any]) -> str | None:
    lifecycle = status["lifecycle"]
    if lifecycle not in ("running", "finished"):
        return None
    game_id = status.get("game_id", "")
    adapter = CLI_GAME_ADAPTERS.get(game_id)
    if adapter is None:
        return None
    state_payload = status.get("state_payload")
    if not isinstance(state_payload, dict):
        return None
    return adapter.renderer(state_payload)


def _render_players(status: Mapping[str, Any]) -> str:
    lifecycle = status["lifecycle"]
    current_seat = status.get("current_seat")
    lines: list[str] = []
    for player in status["players"]:
        seat = player["seat"]
        label = player.get("label") or player["player_id"]
        marker = ""
        if lifecycle == "running" and current_seat == seat:
            marker = f" {CYAN}*{RESET}"
        lines.append(f"  Seat {seat}: {label} ({player['player_id']}){marker}")
    return "\n".join(lines)


def _render_status_line(status: Mapping[str, Any]) -> str:
    turn_count = status["turn_count"]
    current_seat = status.get("current_seat")
    seat_str = str(current_seat) if current_seat is not None else "-"
    return f"Turn {turn_count} — current seat: {seat_str}"


def _render_result(status: Mapping[str, Any]) -> str:
    result = status.get("result")
    if result is None:
        return "Result: (none)"
    payload_str = json.dumps(result.get("payload", {}), sort_keys=True)
    return f"Result: {result['result_type']} {payload_str}"


def _render_abort(status: Mapping[str, Any]) -> str:
    abort = status.get("abort")
    if abort is None:
        return f"{RED}Aborted: (no metadata){RESET}"
    lines: list[str] = [
        f"{RED}Aborted: [{abort['reason']}] {abort['message']}{RESET}"
    ]
    if abort.get("cause_type") is not None:
        cause_msg = abort.get("cause_message") or ""
        lines.append(f"{RED}  Cause: {abort['cause_type']}: {cause_msg}{RESET}")
    return "\n".join(lines)


def _render_runtime_events(transcript: Mapping[str, Any]) -> str:
    events: list[Any] = transcript.get("runtime_events", [])
    if not events:
        return "Runtime events: (none)"
    lines = ["Runtime events:"]
    for event in events:
        payload_str = json.dumps(event.get("payload", {}), sort_keys=True)
        lines.append(f"  [{event['event_type']}] {payload_str}")
    return "\n".join(lines)


def _render_turn_history(transcript: Mapping[str, Any]) -> str:
    turns: list[Any] = transcript.get("turns", [])
    if not turns:
        return "Turn history: (none)"
    lines = ["Turn history:"]
    for turn in turns:
        action_str = json.dumps(turn["action"], sort_keys=True)
        lines.append(f"  #{turn['turn_index']} seat={turn['seat']} action={action_str}")
    return "\n".join(lines)


__all__: tuple[str, ...] = ("render_match_screen",)
