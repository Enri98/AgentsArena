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
                f"Scripted seat {self._seat_index} ran out of actions "
                f"after {self._index} moves."
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


def _build_seat(
    spec: str,
    seat: int,
    game: str,
    label: str,
    ollama_host: str,
    ollama_temperature: float,
    ollama_seed: int,
    ollama_max_retries: int,
    ollama_use_format: bool,
    ollama_timeout: float,
    retry_sink: dict[int, list[tuple[int, str]]],
    decision_sink: dict[int, list[tuple[int, str]]],
) -> tuple[PlayerRecord, Any]:
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
    if spec.startswith("ollama:"):
        model_name = spec[len("ollama:"):]
        return player, _build_ollama_agent(
            model_name=model_name,
            game=game,
            seat=seat,
            host=ollama_host,
            temperature=ollama_temperature,
            seed=ollama_seed,
            max_retries=ollama_max_retries,
            use_format_spec=ollama_use_format,
            timeout=ollama_timeout,
            retry_sink=retry_sink,
            decision_sink=decision_sink,
        )
    raise ValueError(
        f"Unknown seat spec {spec!r}. "
        "Use 'human', 'scripted:<actions>', or 'ollama:<model>'."
    )


def _build_ollama_agent(
    *,
    model_name: str,
    game: str,
    seat: int,
    host: str,
    temperature: float,
    seed: int,
    max_retries: int,
    use_format_spec: bool,
    timeout: float,
    retry_sink: dict[int, list[tuple[int, str]]],
    decision_sink: dict[int, list[tuple[int, str]]],
) -> Any:
    from arena.agents.ollama import OllamaAgent, OllamaClient
    from arena.agents.ollama.connect4 import Connect4PromptBuilder
    from arena.agents.ollama.tictactoe import TicTacToePromptBuilder

    client = OllamaClient(host=host, timeout=timeout)
    builder: Any
    if game == "connect4":
        builder = Connect4PromptBuilder()
    else:
        builder = TicTacToePromptBuilder()

    seat_entries: list[tuple[int, str]] = []
    retry_sink[seat] = seat_entries
    decision_entries: list[tuple[int, str]] = []
    decision_sink[seat] = decision_entries

    def _callback(attempt: int, reason: str) -> None:
        seat_entries.append((attempt, reason))

    def _decision(attempt: int, thought: str) -> None:
        decision_entries.append((attempt, thought))

    return OllamaAgent(
        client=client,
        model=model_name,
        prompt_builder=builder,
        max_retries=max_retries,
        seed=seed,
        temperature=temperature,
        retry_callback=_callback,
        decision_callback=_decision,
        use_format_spec=use_format_spec,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arena.cli.play")
    parser.add_argument("--game", choices=["connect4", "tictactoe"], required=True)
    parser.add_argument("--seat-0", required=True, dest="seat_0")
    parser.add_argument("--seat-1", required=True, dest="seat_1")
    parser.add_argument("--out-dir", default="./out")
    parser.add_argument("--rows", type=int, default=6)
    parser.add_argument("--cols", type=int, default=7)
    parser.add_argument("--connect-length", type=int, default=4, dest="connect_length")
    parser.add_argument("--ollama-host", default="http://localhost:11434", dest="ollama_host")
    parser.add_argument(
        "--ollama-temperature", type=float, default=0.3, dest="ollama_temperature"
    )
    parser.add_argument("--ollama-seed", type=int, default=0, dest="ollama_seed")
    parser.add_argument(
        "--ollama-max-retries", type=int, default=3, dest="ollama_max_retries"
    )
    parser.add_argument(
        "--ollama-no-format",
        action="store_true",
        dest="ollama_no_format",
        help="Disable structured-output format spec (use for older Ollama versions).",
    )
    parser.add_argument(
        "--ollama-timeout",
        type=float,
        default=300.0,
        dest="ollama_timeout",
        help="Per-request HTTP timeout in seconds (raise this for slow cold starts).",
    )
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

    def _seat_label(spec: str) -> str:
        if spec == "human":
            return "Human"
        if spec.startswith("ollama:"):
            return f"Ollama({spec[len('ollama:'):]})"
        return "Scripted"

    retry_sink: dict[int, list[tuple[int, str]]] = {}
    decision_sink: dict[int, list[tuple[int, str]]] = {}

    player0, raw_policy0 = _build_seat(
        args.seat_0, 0, args.game, _seat_label(args.seat_0),
        args.ollama_host, args.ollama_temperature, args.ollama_seed,
        args.ollama_max_retries, not args.ollama_no_format,
        args.ollama_timeout, retry_sink, decision_sink,
    )
    player1, raw_policy1 = _build_seat(
        args.seat_1, 1, args.game, _seat_label(args.seat_1),
        args.ollama_host, args.ollama_temperature, args.ollama_seed,
        args.ollama_max_retries, not args.ollama_no_format,
        args.ollama_timeout, retry_sink, decision_sink,
    )

    ollama_models = [
        spec[len("ollama:"):]
        for spec in (args.seat_0, args.seat_1)
        if spec.startswith("ollama:")
    ]
    if ollama_models:
        from arena.agents.ollama import OllamaUnavailableError, probe_models
        from arena.agents.ollama.exceptions import OllamaModelMissingError

        try:
            probe_models(args.ollama_host, ollama_models)
        except OllamaUnavailableError as exc:
            sys.stderr.write(f"Error: {exc}\n")
            return 2
        except OllamaModelMissingError as exc:
            sys.stderr.write(f"Error: {exc}\n")
            return 2

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
        retry_sink=retry_sink if retry_sink else None,
        decision_sink=decision_sink if decision_sink else None,
    )


if __name__ == "__main__":
    sys.exit(main())
