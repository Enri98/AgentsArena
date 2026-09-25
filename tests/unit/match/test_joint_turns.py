"""Joint turns (Phase 41) through the match layer, transcripts, and replay."""

from __future__ import annotations

import copy
import json
import random
from typing import Any

import pytest

from arena.core.exceptions import WrongPlayer
from arena.games import build_default_registry
from arena.games.rps import Throw
from arena.match import (
    apply_match_action,
    apply_match_joint_action,
    dump_match_transcript,
    run_local_match,
    start_match,
    validate_match_transcript,
)
from arena.match.transcript import (
    dump_match_transcript_for_viewer,
    redact_match_transcript,
)
from arena.runtime.models import PlayerRecord
from arena.runtime.payloads import dump_runtime_transcript, validate_runtime_transcript
from arena.runtime.session import Arena

RPS = build_default_registry().get("rps")


class _Random:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def select_action(self, observation: Any) -> Any:
        return self.rng.choice(observation.legal_actions)


def _match(seed: int = 3, **config: Any) -> Any:
    return run_local_match(
        start_match(RPS, RPS.config_type(**config)), {0: _Random(seed), 1: _Random(seed + 1)}
    )


def _json(value: Any) -> Any:
    return json.loads(json.dumps(value))


def test_a_joint_node_refuses_a_single_seat_action() -> None:
    match = start_match(RPS, RPS.config_type())
    with pytest.raises(WrongPlayer):
        apply_match_action(match, 0, Throw("rock"))


def test_a_round_is_one_turn_carrying_both_throws() -> None:
    match = apply_match_joint_action(
        start_match(RPS, RPS.config_type()), {1: Throw("paper"), 0: Throw("rock")}
    )
    (turn,) = match.turns
    assert (turn.kind, turn.seat, turn.action) == ("joint", None, None)
    assert list(turn.actions) == [0, 1]  # in seat order, whatever order they came in
    assert turn.actions[1] == Throw("paper")


def test_the_transcript_round_trips_and_replays() -> None:
    for seed in range(30):
        match = _match(seed, target_wins=1 + seed % 4, max_rounds=1 + seed % 9)
        payload = _json(dump_match_transcript(match))
        assert payload["schema_version"] == 4
        joint = payload["turns"][0]
        assert joint["kind"] == "joint" and set(joint["actions"]) == {"0", "1"}
        assert joint["seat"] is None and joint["action"] is None
        loaded = validate_match_transcript(RPS, payload)
        assert loaded.turns[0].actions == match.turns[0].actions


def test_a_sequential_turn_carries_no_actions_key() -> None:
    nim = build_default_registry().get("nim")
    match = start_match(nim, nim.config_type())
    match = apply_match_action(match, 0, nim.rules_engine.legal_actions(match.state, 0)[0])
    assert "actions" not in _json(dump_match_transcript(match))["turns"][0]


@pytest.mark.parametrize("viewer", [None, 0, 1])
def test_every_viewer_sees_both_throws_once_the_round_is_resolved(viewer: int | None) -> None:
    match = _match()
    view = _json(dump_match_transcript_for_viewer(match, viewer))
    assert view["turns"][0]["actions"] == _json(dump_match_transcript(match))["turns"][0]["actions"]
    assert redact_match_transcript(RPS, _json(dump_match_transcript(match)), viewer) == view


def _forge(mutate: Any) -> dict:
    payload = _json(dump_match_transcript(_match()))
    mutate(payload["turns"][0])
    return payload


@pytest.mark.parametrize(
    "mutate",
    [
        lambda t: t.update(seat=0),
        lambda t: t.update(action={"shape": "rock"}),
        lambda t: t.update(actions=None),
        lambda t: t.update(actions={"0": {"shape": "rock"}}),  # one seat
        lambda t: t.update(actions={"1": {"shape": "rock"}, "0": {"shape": "rock"}}),  # order
        lambda t: t.update(actions={"00": {"shape": "rock"}, "1": {"shape": "rock"}}),
        lambda t: t.update(actions={"0": {"shape": "lizard"}, "1": {"shape": "rock"}}),
        lambda t: t.update(kind="action"),
        lambda t: t["actions"].__setitem__("0", {"shape": "paper"}),  # changes the outcome
    ],
)
def test_a_forged_joint_turn_is_rejected(mutate: Any) -> None:
    with pytest.raises(ValueError):
        validate_match_transcript(RPS, _forge(mutate))


def test_a_joint_turn_in_an_older_schema_is_rejected() -> None:
    payload = _json(dump_match_transcript(_match()))
    payload["schema_version"] = 3
    with pytest.raises(ValueError):
        validate_match_transcript(RPS, payload)


def test_actions_on_a_sequential_turn_are_rejected() -> None:
    nim = build_default_registry().get("nim")
    match = start_match(nim, nim.config_type())
    match = apply_match_action(match, 0, nim.rules_engine.legal_actions(match.state, 0)[0])
    payload = _json(dump_match_transcript(match))
    payload["turns"][0]["actions"] = {"0": payload["turns"][0]["action"], "1": {}}
    with pytest.raises(ValueError):
        validate_match_transcript(nim, copy.deepcopy(payload))


def test_the_runtime_runs_joint_rounds_with_one_event_pair_per_seat() -> None:
    from arena.adapters.in_process import TypedPayloadPolicyAdapter

    arena = Arena()
    session = arena.create_session(
        RPS,
        RPS.config_type(),
        [PlayerRecord("p0", 0), PlayerRecord("p1", 1)],
        {
            0: TypedPayloadPolicyAdapter(RPS, _Random(1)),
            1: TypedPayloadPolicyAdapter(RPS, _Random(2)),
        },
    )
    session = arena.run_session(session)
    assert session.lifecycle.value == "finished"
    requested = [e for e in session.events if e.event_type == "TurnRequested"]
    accepted = [e for e in session.events if e.event_type == "TurnAccepted"]
    rounds = len(session.local_match.turns)
    assert len(requested) == len(accepted) == 2 * rounds
    assert [e.turn_index for e in accepted[:2]] == [1, 1]
    validate_runtime_transcript(RPS, _json(dump_runtime_transcript(session)))


def test_a_missing_policy_for_an_acting_seat_aborts() -> None:
    from arena.adapters.in_process import TypedPayloadPolicyAdapter

    arena = Arena()
    session = arena.create_session(
        RPS,
        RPS.config_type(),
        [PlayerRecord("p0", 0), PlayerRecord("p1", 1)],
        {0: TypedPayloadPolicyAdapter(RPS, _Random(1))},
    )
    session = arena.run_session(session)
    assert session.abort is not None and session.abort.reason.value == "missing_policy"
