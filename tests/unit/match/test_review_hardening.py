"""Core hardening from the pre-Phase 40 adversarial review.

Phase 40 persists and reloads transcripts, so loading, validating and redacting
them must hold against files nobody vetted. Each test is a confirmed finding.
"""

from __future__ import annotations

import copy
import json
import random
from typing import Any

import pytest

from arena.core.chance import ChanceRng
from arena.core.exceptions import InvalidGameConfig
from arena.games import build_default_registry
from arena.games.liarsdice.audit import leaked_hand_paths
from arena.match import apply_match_action, start_match
from arena.match.transcript import (
    dump_match_transcript,
    redact_match_transcript,
    validate_match_transcript,
)
from arena.runtime.models import PlayerRecord
from arena.runtime.payloads import (
    dump_runtime_transcript,
    dump_session_status,
    redact_runtime_transcript,
    redact_session_status,
    validate_runtime_transcript,
)
from arena.runtime.session import Arena

REGISTRY = build_default_registry()
LIARS = REGISTRY.get("liarsdice")


def _roundtrip(payload: Any) -> Any:
    return json.loads(json.dumps(payload))


def _liars_match(seed: int = 7, *, finish: bool = True) -> Any:
    rnd = random.Random(seed)
    match = start_match(LIARS, LIARS.config_type(dice_per_seat=2), seed=rnd.getrandbits(128))
    engine = match.rules_engine
    for _ in range(400):
        if engine.is_terminal(match.state):
            break
        seat = engine.current_seat(match.state)
        legal = engine.legal_actions(match.state, seat)
        if finish and len(match.state.bids) >= 2:
            action = legal[0]  # call: rounds end, so the match finishes
        else:
            action = rnd.choice(legal[1:4] or legal)
        match = apply_match_action(match, seat, action)
    return match


def _session(match: Any, *, finished: bool = True) -> Any:
    from dataclasses import replace

    from arena.runtime.models import RuntimeLifecycle

    arena = Arena()
    session = arena.create_session(
        LIARS,
        match.config,
        [PlayerRecord(player_id="p0", seat=0), PlayerRecord(player_id="p1", seat=1)],
        {},
    )
    return replace(
        session,
        local_match=match,
        lifecycle=RuntimeLifecycle.FINISHED if finished else RuntimeLifecycle.RUNNING,
    )


# ── Redaction decides visibility from the replayed game ──────────────────────


def _strip_markers(transcript: dict) -> dict:
    stripped = copy.deepcopy(transcript)
    for turn in stripped["turns"]:
        for event in turn["events"]:
            event.pop("is_public", None)
            event.pop("audience", None)
    return stripped


def test_redaction_refuses_a_transcript_whose_visibility_markers_were_stripped() -> None:
    full = _roundtrip(dump_match_transcript(_liars_match()))
    with pytest.raises(ValueError):
        redact_match_transcript(LIARS, _strip_markers(full), None)


def test_redaction_refuses_a_widened_audience() -> None:
    full = _roundtrip(dump_match_transcript(_liars_match()))
    for turn in full["turns"]:
        for event in turn["events"]:
            if event["event_type"] == "DiceDealt":
                event["audience"] = [0, 1]
    with pytest.raises(ValueError):
        redact_match_transcript(LIARS, full, 0)


def test_redaction_of_an_honest_transcript_leaks_nothing() -> None:
    full = _roundtrip(dump_match_transcript(_liars_match()))
    assert leaked_hand_paths(redact_match_transcript(LIARS, full, None), None) == []
    assert leaked_hand_paths(redact_match_transcript(LIARS, full, 1), 1) == []


# ── Malformed transcripts fail with ValueError ───────────────────────────────


def test_a_win_without_a_seat_is_a_value_error() -> None:
    full = _roundtrip(dump_match_transcript(_liars_match()))
    last = full["turns"][-1]
    assert last["result"]["result_type"] == "Win"
    del last["result"]["payload"]["seat"]
    with pytest.raises(ValueError):
        validate_match_transcript(LIARS, full)
    with pytest.raises(ValueError):
        redact_match_transcript(LIARS, full, None)


@pytest.mark.parametrize("hands", [[[1, 2]], [[1, 2], [3, 4], [5, 6]]])
def test_a_liars_dice_state_needs_exactly_two_hands(hands: list) -> None:
    full = _roundtrip(dump_match_transcript(_liars_match()))
    for turn in full["turns"]:
        if turn["post_snapshot"]["state"]["dice"] is not None:
            turn["post_snapshot"]["state"]["dice"] = hands
            break
    with pytest.raises(ValueError):
        validate_match_transcript(LIARS, full)


# ── The runtime envelope agrees with itself and with its contents ────────────


@pytest.mark.parametrize(
    "patch",
    [
        {"view": "public"},  # a "public" label around a full transcript
        {"view": "seat", "viewer_seat": None},
        {"viewer_seat": 7},
        {"lifecycle": "banana"},
        {"lifecycle": "running"},  # the game is over
        {"abort": {"reason": "nope", "message": "m"}},  # finished, yet aborted
        {"players": [{"player_id": "a", "seat": 0}, {"player_id": "a", "seat": 0}]},
    ],
)
def test_an_inconsistent_runtime_transcript_is_rejected(patch: dict) -> None:
    doc = _roundtrip(dump_runtime_transcript(_session(_liars_match())))
    doc.update(patch)
    with pytest.raises(ValueError):
        validate_runtime_transcript(LIARS, doc)


def test_an_unknown_abort_reason_is_rejected_on_validation() -> None:
    doc = _roundtrip(dump_runtime_transcript(_session(_liars_match(finish=False), finished=False)))
    doc.update(lifecycle="aborted", abort={"reason": "nope", "message": "m"})
    with pytest.raises(ValueError):
        validate_runtime_transcript(LIARS, doc)


# ── An abort's cause text stays out of non-full views ────────────────────────


def _aborted_session() -> Any:
    from arena.runtime.models import AbortReason
    from arena.runtime.session import _abort_session

    # What a local run records when a seat's policy raises (session.py).
    session = _session(_liars_match(finish=False), finished=False)
    return _abort_session(
        session,
        reason=AbortReason.ADAPTER_ERROR,
        message="The active policy failed to produce a valid action response.",
        cause=RuntimeError('Raw content: {"thought": "I hold two 5s"}'),
    )


def _cause_messages(payload: Any) -> list[Any]:
    found: list[Any] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "cause_message" in value:
                found.append(value["cause_message"])
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(payload)
    return found


@pytest.mark.parametrize("viewer", [None, 0, 1])
def test_an_abort_cause_is_not_in_a_seat_or_public_view(viewer: int | None) -> None:
    session = _aborted_session()
    for payload in (
        dump_runtime_transcript(session, viewer=viewer),
        dump_session_status(session, viewer=viewer),
        redact_runtime_transcript(LIARS, _roundtrip(dump_runtime_transcript(session)), viewer),
        redact_session_status(LIARS, _roundtrip(dump_session_status(session)), viewer),
    ):
        causes = _cause_messages(payload)
        assert causes and all(cause is None for cause in causes), causes


def test_the_full_view_keeps_the_abort_cause() -> None:
    causes = _cause_messages(dump_runtime_transcript(_aborted_session()))
    assert any(cause and "Raw content" in cause for cause in causes)


# ── Game states no match can reach do not load ───────────────────────────────


_LIARS_BASE = {
    "dice": None,
    "dice_counts": [2, 2],
    "bids": [],
    "current_seat": 0,
    "round_number": 1,
    "faces": 6,
    "last_showdown": None,
}


@pytest.mark.parametrize(
    "patch",
    [
        {"dice_counts": [50, 50]},
        {"dice_counts": [0, 0]},
        {"dice_counts": [0, 2], "current_seat": 0},  # the loser to move at the end
        {"dice_counts": [0, 2], "current_seat": 1, "dice": [[], [1, 2]]},
        {"bids": [{"quantity": 1, "face": 2}]},  # a bid before the roll
        {"round_number": 0, "last_showdown": {
            "caller": 0, "bid": {"quantity": 1, "face": 2},
            "dice": [[2], [3]], "count": 1, "loser": 0,
        }},
        {"last_showdown": {
            "caller": 0, "bid": {"quantity": 1, "face": 7},
            "dice": [[7], [3]], "count": 1, "loser": 0,
        }},
    ],
)
def test_an_unreachable_liars_dice_state_does_not_load(patch: dict) -> None:
    with pytest.raises(Exception) as info:
        LIARS.serializer.load_state({**_LIARS_BASE, **patch})
    assert not isinstance(info.value, (KeyError, IndexError, TypeError))


def test_every_reachable_liars_dice_state_loads() -> None:
    for seed in range(40):
        match = _liars_match(seed)
        for turn in match.turns:
            dumped = LIARS.serializer.dump_state(turn.post_state)
            assert LIARS.serializer.load_state(dumped) == turn.post_state


_PIG = REGISTRY.get("pig")
_PIG_BASE = {
    "scores": [0, 0],
    "current_seat": 0,
    "turn_total": 0,
    "roll_pending": False,
    "target_score": 20,
}


@pytest.mark.parametrize(
    "patch",
    [
        {"scores": [20, 25]},
        {"scores": [25, 0], "roll_pending": True},
        {"scores": [25, 0], "current_seat": 1},
        {"scores": [25, 0], "turn_total": 4},
        {"target_score": 10**9},
    ],
)
def test_an_unreachable_pig_state_does_not_load(patch: dict) -> None:
    with pytest.raises(Exception) as info:
        _PIG.serializer.load_state({**_PIG_BASE, **patch})
    assert not isinstance(info.value, (KeyError, IndexError, TypeError))


def test_a_finished_pig_state_loads() -> None:
    state = _PIG.serializer.load_state({**_PIG_BASE, "scores": [25, 3]})
    assert _PIG.rules_engine.is_terminal(state)


# ── ChanceRng ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("bound", [0, -1, 2**64 + 1, 1.5, True])
def test_a_draw_bound_outside_one_word_is_refused(bound: Any) -> None:
    with pytest.raises(ValueError):
        ChanceRng(seed=1).draw(bound)


def test_a_draw_at_the_word_limit_still_works() -> None:
    value, _ = ChanceRng(seed=1).draw(2**64)
    assert 0 <= value < 2**64


@pytest.mark.parametrize(
    "payload",
    [{"seed": 1.9, "counter": 3}, {"seed": 1, "counter": "3"}, {"seed": True, "counter": 0}],
)
def test_loading_a_generator_does_not_coerce(payload: dict) -> None:
    with pytest.raises(InvalidGameConfig) as info:
        ChanceRng.load(payload)
    assert "1" not in json.dumps(info.value.details or {})  # the seed stays out of errors
