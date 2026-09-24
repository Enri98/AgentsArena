"""The hand-leak auditor used by the wire tests and the demo."""

from __future__ import annotations

from arena.games.liarsdice.audit import leaked_hand_paths


def test_legitimate_hands_pass() -> None:
    frame = {
        "post_snapshot": {
            "state": {"my_dice": [1, 2], "seat": 0, "last_showdown": {"dice": [[1], [2]]}}
        },
        "events": [
            {"event_type": "BidCalled", "payload": {"dice": [[1, 2], [3, 4]]}},
            {"event_type": "DiceDealt", "payload": {"seat": 0, "dice": [1, 2]}},
        ],
        "outcome": {"my_dice": [1, 2]},
    }
    assert leaked_hand_paths(frame, 0) == []


def test_each_leak_shape_is_caught() -> None:
    assert leaked_hand_paths({"state": {"dice": [[1], [2]]}}, 0) == ["$.state.dice"]
    assert leaked_hand_paths(
        {"events": [{"event_type": "DiceDealt", "payload": {"seat": 1, "dice": [3]}}]}, 0
    ) == ["$.events[0] (DiceDealt for seat 1)"]
    assert leaked_hand_paths({"outcome": {"my_dice": [1]}}, None) == ["$.outcome.my_dice"]
    assert leaked_hand_paths({"outcome": {"dice": [[1], [2]]}}, 1) == ["$.outcome.dice"]


def test_a_pending_roll_is_not_a_leak() -> None:
    assert leaked_hand_paths({"state": {"dice": None, "my_dice": []}}, None) == []
