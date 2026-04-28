"""Golden-output tests for the arena.cli screen renderer (Slice 2, no board)."""

from __future__ import annotations

from dataclasses import dataclass, field

from arena.adapters import TypedPayloadPolicyAdapter
from arena.cli.rendering import render_match_screen
from arena.games.connect4 import (
    Connect4Config,
    Connect4GameDefinition,
    Connect4Observation,
    DropDisc,
)
from arena.runtime import (
    Arena,
    MatchId,
    PlayerRecord,
    dump_runtime_transcript,
    dump_session_status,
)
from arena.ui import build_match_screen

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RED = "\x1b[31m"
YELLOW = "\x1b[33m"
GREEN = "\x1b[32m"
BLUE = "\x1b[34m"
CYAN = "\x1b[36m"

EM = "—"

# Board cell glyphs used in golden board sections.
_E = f"{DIM}.{RESET}"
_S0 = f"{RED}●{RESET}"
_S1 = f"{YELLOW}●{RESET}"


def _c4_board_6x7_after_seat0_col0() -> str:
    """Board after seat 0 drops in column 0 on a default 6x7 board."""
    empty_row = " ".join(_E for _ in range(7))
    bottom_row = f"{_S0} " + " ".join(_E for _ in range(6))
    return (
        f"{DIM}0 1 2 3 4 5 6{RESET}\n"
        + "\n".join(empty_row for _ in range(5))
        + f"\n{bottom_row}"
    )


def _c4_board_4x4_seat0_wins_col0() -> str:
    """Final board state: seat0 wins with 4 in column 0 on a 4x4 board."""
    return (
        f"{DIM}0 1 2 3{RESET}\n"
        f"{_S0} {_E} {_E} {_E}\n"
        f"{_S0} {_S1} {_E} {_E}\n"
        f"{_S0} {_S1} {_E} {_E}\n"
        f"{_S0} {_S1} {_E} {_E}"
    )


@dataclass
class _ScriptedAgent:
    actions: tuple[DropDisc, ...]
    observations: list[Connect4Observation] = field(default_factory=list)
    index: int = 0

    def select_action(self, observation: Connect4Observation) -> DropDisc:
        self.observations.append(observation)
        action = self.actions[self.index]
        self.index += 1
        return action


def _players() -> tuple[PlayerRecord, PlayerRecord]:
    return (
        PlayerRecord(player_id="player-0", label="Red", seat=0),
        PlayerRecord(player_id="player-1", label="Yellow", seat=1),
    )


def _winning_policies() -> dict[int, TypedPayloadPolicyAdapter]:
    return {
        0: TypedPayloadPolicyAdapter(
            Connect4GameDefinition,
            _ScriptedAgent(
                actions=(
                    DropDisc(column=0),
                    DropDisc(column=0),
                    DropDisc(column=0),
                    DropDisc(column=0),
                )
            ),
        ),
        1: TypedPayloadPolicyAdapter(
            Connect4GameDefinition,
            _ScriptedAgent(
                actions=(
                    DropDisc(column=1),
                    DropDisc(column=1),
                    DropDisc(column=1),
                )
            ),
        ),
    }


def _running_screen_after_one_move() -> dict:
    arena = Arena(id_factory=lambda: MatchId("test-running"))
    session = arena.start_session(
        arena.create_session(
            Connect4GameDefinition, Connect4Config(), _players(), _winning_policies()
        )
    )
    after1 = arena.step_session(session)
    return build_match_screen(
        status_payload=dump_session_status(after1),
        transcript_payload=dump_runtime_transcript(after1),
    )


def _finished_screen() -> dict:
    arena = Arena(id_factory=lambda: MatchId("test-finished"))
    session = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            _players(),
            _winning_policies(),
        )
    )
    return build_match_screen(
        status_payload=dump_session_status(session),
        transcript_payload=dump_runtime_transcript(session),
    )


def _aborted_screen() -> dict:
    arena = Arena(id_factory=lambda: MatchId("test-aborted"))
    running = arena.start_session(
        arena.create_session(Connect4GameDefinition, Connect4Config(), _players(), {})
    )
    aborted = arena.step_session(running)
    return build_match_screen(
        status_payload=dump_session_status(aborted),
        transcript_payload=dump_runtime_transcript(aborted),
    )


# ---------------------------------------------------------------------------
# Helpers that build expected strings in the same way the renderer does,
# so that if ANSI constants change both sides change together.
# ---------------------------------------------------------------------------

# Shared sub-strings reused across golden strings.
_PLAYERS_JSON = (
    '{"players": ['
    '{"label": "Red", "player_id": "player-0", "seat": 0}, '
    '{"label": "Yellow", "player_id": "player-1", "seat": 1}'
    "]}"
)
_ABORT_JSON = (
    '{"abort": {'
    '"cause_message": null, "cause_type": null, '
    '"message": "No policy is bound for active seat 0.", '
    '"reason": "missing_policy"'
    "}}"
)

_RUNNING_EXPECTED = (
    f"{BOLD}Match test-running {EM} connect4{RESET}  {GREEN}running{RESET}\n"
    + _c4_board_6x7_after_seat0_col0()
    + "\n"
    + f"  Seat 0: Red (player-0)\n"
    f"  Seat 1: Yellow (player-1) {CYAN}*{RESET}\n"
    f"Turn 1 {EM} current seat: 1\n"
    f"Runtime events:\n"
    f"  [MatchCreated] {_PLAYERS_JSON}\n"
    f"  [MatchStarted] {{}}\n"
    f'  [TurnRequested] {{"seat": 0}}\n'
    f'  [TurnAccepted] {{"seat": 0, "turn_index": 1}}\n'
    f"Turn history:\n"
    f'  #1 seat=0 action={{"column": 0}}'
)

_FINISHED_EXPECTED = (
    f"{BOLD}Match test-finished {EM} connect4{RESET}  {BLUE}finished{RESET}\n"
    + _c4_board_4x4_seat0_wins_col0()
    + "\n"
    + f"  Seat 0: Red (player-0)\n"
    f"  Seat 1: Yellow (player-1)\n"
    f"Turn 7 {EM} current seat: -\n"
    f'Result: Win {{"seat": 0}}\n'
    f"Runtime events:\n"
    f"  [MatchCreated] {_PLAYERS_JSON}\n"
    f"  [MatchStarted] {{}}\n"
    f'  [TurnRequested] {{"seat": 0}}\n'
    f'  [TurnAccepted] {{"seat": 0, "turn_index": 1}}\n'
    f'  [TurnRequested] {{"seat": 1}}\n'
    f'  [TurnAccepted] {{"seat": 1, "turn_index": 2}}\n'
    f'  [TurnRequested] {{"seat": 0}}\n'
    f'  [TurnAccepted] {{"seat": 0, "turn_index": 3}}\n'
    f'  [TurnRequested] {{"seat": 1}}\n'
    f'  [TurnAccepted] {{"seat": 1, "turn_index": 4}}\n'
    f'  [TurnRequested] {{"seat": 0}}\n'
    f'  [TurnAccepted] {{"seat": 0, "turn_index": 5}}\n'
    f'  [TurnRequested] {{"seat": 1}}\n'
    f'  [TurnAccepted] {{"seat": 1, "turn_index": 6}}\n'
    f'  [TurnRequested] {{"seat": 0}}\n'
    f'  [TurnAccepted] {{"seat": 0, "turn_index": 7}}\n'
    f"  [MatchFinished] {{}}\n"
    f"Turn history:\n"
    f'  #1 seat=0 action={{"column": 0}}\n'
    f'  #2 seat=1 action={{"column": 1}}\n'
    f'  #3 seat=0 action={{"column": 0}}\n'
    f'  #4 seat=1 action={{"column": 1}}\n'
    f'  #5 seat=0 action={{"column": 0}}\n'
    f'  #6 seat=1 action={{"column": 1}}\n'
    f'  #7 seat=0 action={{"column": 0}}'
)

_ABORTED_EXPECTED = (
    f"{BOLD}Match test-aborted {EM} connect4{RESET}  {RED}aborted{RESET}\n"
    f"  Seat 0: Red (player-0)\n"
    f"  Seat 1: Yellow (player-1)\n"
    f"Turn 0 {EM} current seat: 0\n"
    f"{RED}Aborted: [missing_policy] No policy is bound for active seat 0.{RESET}\n"
    f"Runtime events:\n"
    f"  [MatchCreated] {_PLAYERS_JSON}\n"
    f"  [MatchStarted] {{}}\n"
    f'  [TurnRequested] {{"seat": 0}}\n'
    f"  [MatchAborted] {_ABORT_JSON}\n"
    f"Turn history: (none)"
)


def test_render_running_session_golden() -> None:
    screen = _running_screen_after_one_move()
    result = render_match_screen(screen)
    assert result == _RUNNING_EXPECTED


def test_render_running_session_is_deterministic() -> None:
    screen = _running_screen_after_one_move()
    assert render_match_screen(screen) == render_match_screen(screen)


def test_render_finished_session_golden() -> None:
    screen = _finished_screen()
    result = render_match_screen(screen)
    assert result == _FINISHED_EXPECTED


def test_render_finished_session_is_deterministic() -> None:
    screen = _finished_screen()
    assert render_match_screen(screen) == render_match_screen(screen)


def test_render_aborted_session_golden() -> None:
    screen = _aborted_screen()
    result = render_match_screen(screen)
    assert result == _ABORTED_EXPECTED


def test_render_aborted_session_is_deterministic() -> None:
    screen = _aborted_screen()
    assert render_match_screen(screen) == render_match_screen(screen)
