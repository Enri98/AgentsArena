"""CLI entrypoint: python -m arena.cli.play."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from arena.cli.games import connect4 as _c4_renderer
from arena.cli.games import tictactoe as _ttt_renderer
from arena.cli.play import play_match
from arena.cli.policies import HumanPolicy
from arena.runtime import PlayerRecord


class _ScriptedPolicy:
    """Emit a fixed sequence of pre-parsed typed actions."""

    def __init__(self, actions: list[Any], seat_index: int = 0) -> None:
        self._actions = list(actions)
        self._index = 0
        self._seat_index = seat_index

    def select_action(self, observation: Any) -> Any:
        if self._index >= len(self._actions):
            raise RuntimeError(
                f"Scripted seat {self._seat_index} ran out of actions after {self._index} moves."
            )
        action = self._actions[self._index]
        self._index += 1
        return action


def _parse_scripted_connect4(spec: str) -> list[Any]:
    from arena.games.connect4 import DropDisc

    return [DropDisc(column=int(v.strip())) for v in spec.split(",") if v.strip()]


def _parse_scripted_tictactoe(spec: str) -> list[Any]:
    from arena.cli.games.tictactoe import numpad_action

    actions = []
    for v in spec.split(","):
        v = v.strip()
        if not v:
            continue
        actions.append(numpad_action(int(v)))
    return actions


def _build_seat(spec: str, seat: int, game: str, label: str) -> tuple[PlayerRecord, Any]:
    player = PlayerRecord(player_id=f"player-{seat}", seat=seat, label=label)
    if spec == "human":
        return player, None
    if spec.startswith("scripted:"):
        raw = spec[len("scripted:"):]
        if game == "connect4":
            actions = _parse_scripted_connect4(raw)
        else:
            actions = _parse_scripted_tictactoe(raw)
        return player, _ScriptedPolicy(actions, seat_index=seat)
    raise ValueError(f"Unknown seat spec {spec!r}. Use 'human' or 'scripted:<actions>'.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arena.cli.play")
    parser.add_argument("--game", choices=["connect4", "tictactoe"], required=True)
    parser.add_argument("--seat-0", required=True, dest="seat_0")
    parser.add_argument("--seat-1", required=True, dest="seat_1")
    parser.add_argument("--out-dir", default="./out")
    parser.add_argument("--rows", type=int, default=6)
    parser.add_argument("--cols", type=int, default=7)
    parser.add_argument("--connect-length", type=int, default=4, dest="connect_length")
    args = parser.parse_args(argv)

    if args.game == "connect4":
        from arena.games.connect4 import Connect4Config, Connect4GameDefinition

        definition = Connect4GameDefinition
        config = Connect4Config(
            rows=args.rows, columns=args.cols, connect_length=args.connect_length
        )
        parser_fn = _c4_renderer.parse_input
    else:
        from arena.games.tictactoe import TicTacToeConfig, TicTacToeGameDefinition

        definition = TicTacToeGameDefinition
        config = TicTacToeConfig()
        parser_fn = _ttt_renderer.parse_input

    label0 = "Human" if args.seat_0 == "human" else "Scripted"
    label1 = "Human" if args.seat_1 == "human" else "Scripted"

    player0, raw_policy0 = _build_seat(args.seat_0, 0, args.game, label0)
    player1, raw_policy1 = _build_seat(args.seat_1, 1, args.game, label1)

    from arena.adapters.in_process import TypedPayloadPolicyAdapter

    def _wrap(raw: Any, seat: int) -> Any:
        if raw is None:
            policy = HumanPolicy(parser_fn, stdin=sys.stdin, stdout=sys.stdout)
            return TypedPayloadPolicyAdapter(definition, policy)
        return TypedPayloadPolicyAdapter(definition, raw)

    policies = {0: _wrap(raw_policy0, 0), 1: _wrap(raw_policy1, 1)}

    return play_match(
        definition,
        config,
        (player0, player1),
        policies,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    sys.exit(main())
