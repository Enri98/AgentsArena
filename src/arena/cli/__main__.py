"""python -m arena.cli entrypoint for the terminal replay viewer."""

from __future__ import annotations

import argparse
import sys

from arena._entry import program_name
from arena.cli.app import render_all_frames, render_session_from_files


def _seat(text: str) -> int:
    try:
        seat = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a seat: {text!r}") from None
    if seat not in (0, 1):
        raise argparse.ArgumentTypeError("a seat is 0 or 1")
    return seat


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=program_name("python -m arena.cli"),
        description="Render a saved arena session from status + transcript JSON files.",
    )
    parser.add_argument(
        "--status", required=True, metavar="PATH", help="Runtime status JSON file."
    )
    parser.add_argument(
        "--transcript", required=True, metavar="PATH", help="Runtime transcript JSON file."
    )
    parser.add_argument(
        "--seat",
        type=_seat,
        metavar="N",
        help=(
            "Render seat N's view: what that seat could see during the match. "
            "Redacts a full transcript of a hidden-information game."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--turn", type=int, metavar="N", help="Render a single turn frame N.")
    mode.add_argument("--all-frames", action="store_true", help="Render all turn frames.")
    return parser


def _tolerate_unencodable_output() -> None:
    """Boards use glyphs like ● that a cp1252 Windows console cannot encode;
    replace them rather than crash mid-match."""

    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> None:
    _tolerate_unencodable_output()
    args = _build_parser().parse_args(argv)
    if args.all_frames:
        print(render_all_frames(args.status, args.transcript, seat=args.seat))
    else:
        print(
            render_session_from_files(
                args.status, args.transcript, turn=args.turn, seat=args.seat
            )
        )


if __name__ == "__main__":
    main(sys.argv[1:])
