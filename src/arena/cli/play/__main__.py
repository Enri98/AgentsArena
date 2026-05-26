"""CLI entrypoint: python -m arena.cli.play."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from typing import Any

from arena.cli.games import CLI_GAME_ADAPTERS, cli_game_ids, get_cli_adapter
from arena.cli.play import play_match
from arena.cli.policies import HumanPolicy
from arena.games import build_default_registry
from arena.runtime import PlayerRecord

_GAME_DEFINITION_REGISTRY = build_default_registry()


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
        actions = get_cli_adapter(game).scripted_parser(raw)
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
    from arena.agents.ollama._adapters import OLLAMA_GAME_ADAPTERS

    client = OllamaClient(host=host, timeout=timeout)
    builder: Any = OLLAMA_GAME_ADAPTERS[game].prompt_builder_factory()

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


def _ws_to_http(ws_url: str) -> str:
    """Convert a WebSocket base URL to its HTTP equivalent for REST calls."""
    if ws_url.startswith("wss://"):
        return "https://" + ws_url[len("wss://"):]
    if ws_url.startswith("ws://"):
        return "http://" + ws_url[len("ws://"):]
    return ws_url


def _create_remote_match(http_base: str, game_id: str, config_dict: dict, players: list) -> dict:
    """POST /matches and return the parsed response body."""
    body = json.dumps(
        {"game_id": game_id, "game_config": config_dict, "players": players}
    ).encode()
    req = urllib.request.Request(
        f"{http_base}/matches",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        return json.loads(resp.read())


def _raw_agent_choose(raw_agent: Any, definition: Any) -> Any:
    """Build a choose() callable from a typed agent or raise for unsupported specs."""
    from arena.cli.remote import make_typed_agent_choose

    return make_typed_agent_choose(raw_agent, definition)


def _run_remote(
    *,
    args: Any,
    definition: Any,
    config: Any,
    raw_policy0: Any,
    raw_policy1: Any,
    player0: PlayerRecord,
    player1: PlayerRecord,
) -> int:
    """Create a match on arena.server and connect all seats remotely."""
    for seat, spec, policy in [(0, args.seat_0, raw_policy0), (1, args.seat_1, raw_policy1)]:
        if spec == "human":
            sys.stderr.write(
                f"Error: seat {seat} is 'human' but --server-url is set. "
                "Human play is not supported in remote mode.\n"
            )
            return 2
        if policy is None:
            sys.stderr.write(
                f"Error: seat {seat} produced no policy for remote mode.\n"
            )
            return 2

    http_base = _ws_to_http(args.server_url.rstrip("/"))

    config_dict = config.model_dump(mode="json") if hasattr(config, "model_dump") else {}

    players = [
        {"label": player0.label},
        {"label": player1.label},
    ]

    try:
        match_info = _create_remote_match(http_base, args.game, config_dict, players)
    except Exception as exc:
        sys.stderr.write(f"Error: failed to create remote match: {exc}\n")
        return 2

    seat_0_url = match_info["seat_0_url"]
    seat_1_url = match_info["seat_1_url"]
    match_id = match_info["match_id"]

    sys.stdout.write(f"Remote match created: {match_id}\n")
    sys.stdout.write(f"  seat 0: {seat_0_url}\n")
    sys.stdout.write(f"  seat 1: {seat_1_url}\n")
    sys.stdout.flush()

    from arena.cli.remote import run_remote_seats_sync

    choose0 = _raw_agent_choose(raw_policy0, definition)
    choose1 = _raw_agent_choose(raw_policy1, definition)

    try:
        results = run_remote_seats_sync(
            [seat_0_url, seat_1_url],
            [choose0, choose1],
        )
    except Exception as exc:
        sys.stderr.write(f"Error: remote match failed: {exc}\n")
        return 1

    (result0, transcript0), (result1, transcript1) = results

    import os

    out_path = args.out_dir
    os.makedirs(out_path, exist_ok=True)

    transcript_data = (
        transcript0.model_dump(mode="json") if hasattr(transcript0, "model_dump") else {}
    )
    with open(os.path.join(out_path, "transcript.json"), "w", encoding="utf-8") as f:
        json.dump(transcript_data, f, indent=2)

    lifecycle = getattr(transcript0, "lifecycle", None)
    sys.stdout.write(f"Match finished. Lifecycle: {lifecycle}\n")
    sys.stdout.flush()

    return 0 if lifecycle == "finished" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m arena.cli.play")
    parser.add_argument("--game", choices=sorted(cli_game_ids()), required=True)
    parser.add_argument("--seat-0", required=True, dest="seat_0")
    parser.add_argument("--seat-1", required=True, dest="seat_1")
    parser.add_argument("--out-dir", default="./out")
    parser.add_argument("--rows", type=int, default=6)
    parser.add_argument("--cols", type=int, default=7)
    parser.add_argument("--connect-length", type=int, default=4, dest="connect_length")
    parser.add_argument("--nim-piles", type=int, default=3, dest="nim_piles")
    parser.add_argument(
        "--nim-pile-size", type=int, default=7, dest="nim_pile_size"
    )
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
    parser.add_argument(
        "--server-url",
        default=None,
        dest="server_url",
        help=(
            "WebSocket base URL of a running arena.server, e.g. ws://127.0.0.1:8080. "
            "When present all seats connect to the remote server instead of running "
            "in-process. Ollama probe is still performed locally before connecting."
        ),
    )
    args = parser.parse_args(argv)

    cli_adapter = CLI_GAME_ADAPTERS[args.game]
    definition = _GAME_DEFINITION_REGISTRY.get(args.game)
    config = cli_adapter.config_factory(args)
    parser_fn = cli_adapter.human_parser

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

    if args.server_url:
        return _run_remote(
            args=args,
            definition=definition,
            config=config,
            raw_policy0=raw_policy0,
            raw_policy1=raw_policy1,
            player0=player0,
            player1=player1,
        )

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
