"""python -m arena.cli entrypoint for the terminal replay viewer."""

from __future__ import annotations

import argparse
import sys

from arena.cli.app import render_all_frames, render_session_from_files


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m arena.cli",
        description="Render a saved arena session from status + transcript JSON files.",
    )
    parser.add_argument(
        "--status", required=True, metavar="PATH", help="Runtime status JSON file."
    )
    parser.add_argument(
        "--transcript", required=True, metavar="PATH", help="Runtime transcript JSON file."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--turn", type=int, metavar="N", help="Render a single turn frame N.")
    mode.add_argument("--all-frames", action="store_true", help="Render all turn frames.")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    if args.all_frames:
        print(render_all_frames(args.status, args.transcript))
    else:
        print(render_session_from_files(args.status, args.transcript, turn=args.turn))


if __name__ == "__main__":
    main(sys.argv[1:])
