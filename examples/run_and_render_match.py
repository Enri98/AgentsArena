"""End-to-end example: run a scripted Connect 4 session, dump payloads, and render."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from arena.adapters import TypedPayloadPolicyAdapter
from arena.cli.app import render_session_from_files
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


@dataclass
class ScriptedAgent:
    actions: tuple[DropDisc, ...]
    index: int = 0

    def select_action(self, observation: Connect4Observation) -> DropDisc:
        action = self.actions[self.index]
        self.index += 1
        return action


def run_and_render(out_dir: str | os.PathLike[str]) -> str:
    """Run a scripted Connect 4 session, dump payloads, and return the rendered output."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    arena = Arena(id_factory=lambda: MatchId("example-match"))
    session = arena.run_session(
        arena.create_session(
            Connect4GameDefinition,
            Connect4Config(rows=4, columns=4, connect_length=4),
            players=(
                PlayerRecord(player_id="player-0", label="Red", seat=0),
                PlayerRecord(player_id="player-1", label="Yellow", seat=1),
            ),
            policy_bindings={
                0: TypedPayloadPolicyAdapter(
                    Connect4GameDefinition,
                    ScriptedAgent(
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
                    ScriptedAgent(
                        actions=(
                            DropDisc(column=1),
                            DropDisc(column=1),
                            DropDisc(column=1),
                        )
                    ),
                ),
            },
        )
    )

    status_path = out_path / "status.json"
    transcript_path = out_path / "transcript.json"

    status_path.write_text(
        json.dumps(dump_session_status(session), indent=2), encoding="utf-8"
    )
    transcript_path.write_text(
        json.dumps(dump_runtime_transcript(session), indent=2), encoding="utf-8"
    )

    rendered = render_session_from_files(status_path, transcript_path)
    return rendered


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a scripted Connect 4 match and render the final frame."
    )
    parser.add_argument(
        "--out-dir",
        default="./out",
        metavar="DIR",
        help="Directory to write status.json and transcript.json (default: ./out).",
    )
    args = parser.parse_args()
    print(run_and_render(args.out_dir))


if __name__ == "__main__":
    main()
