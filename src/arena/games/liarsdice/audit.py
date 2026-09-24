"""Audit a JSON payload for Liar's Dice hands a viewer may not see.

Used by the wire tests and by ``examples/run_liarsdice_demo.py`` to check what a
client actually received. Hands may legitimately appear in exactly three places:

* a showdown: a ``BidCalled`` event, or ``last_showdown``, both public by design;
* the viewer's own hand, as ``my_dice`` in its seat view or roll outcome;
* the viewer's own ``DiceDealt`` event.

Anything else carrying a hand (a ``dice`` key, another seat's ``DiceDealt``, or
``my_dice`` in a payload built for the public) is reported.

This is a *structural* check with known limits: it trusts that ``my_dice`` is
the viewer's own hand, and it only knows the key names this game uses (a hand
under an unexpected key would pass). The wire tests close the first gap with
ground truth from the server's full transcript, checking every ``my_dice`` a
seat receives against that seat's actual hand for that round; the
indistinguishability test closes the second for round 1 of a scripted match.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def leaked_hand_paths(payload: Any, viewer: int | None) -> list[str]:
    """Paths in ``payload`` where a hand appears that ``viewer`` may not see.

    ``viewer`` is the receiving seat, or ``None`` for a spectator.
    """

    found: list[str] = []
    _walk(payload, viewer, "$", found)
    return found


def _walk(value: Any, viewer: int | None, path: str, found: list[str]) -> None:
    if isinstance(value, list):
        for index, item in enumerate(value):
            _walk(item, viewer, f"{path}[{index}]", found)
        return
    if not isinstance(value, dict):
        return

    event_type = value.get("event_type")
    if event_type == "BidCalled":
        return  # the showdown: public by design
    if event_type == "DiceDealt":
        seat = (value.get("payload") or {}).get("seat")
        if viewer is None or seat != viewer:
            found.append(f"{path} (DiceDealt for seat {seat})")
        return

    for key, item in value.items():
        child = f"{path}.{key}"
        if key == "last_showdown":
            continue
        if key == "dice" and item is not None:
            found.append(child)
            continue
        if key == "my_dice" and viewer is None and item:
            found.append(child)
            continue
        _walk(item, viewer, child, found)


__all__: Sequence[str] = ["leaked_hand_paths"]
