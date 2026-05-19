"""Shared helpers for building scripted server message sequences."""
from __future__ import annotations

from arena.adapters.websocket.envelope import (
    MatchAbortedEnvelope,
    MatchFinishedEnvelope,
    MatchStateEnvelope,
    ObservationRequestEnvelope,
    TurnCommittedEnvelope,
)
from arena.adapters.websocket.messages import (
    MatchAbortedBody,
    MatchFinishedBody,
    MatchStateBody,
    ObservationRequestBody,
    TurnCommittedBody,
)

MATCH_ID = "test-match-id"
GAME_ID = "connect4"

# Minimal valid RuntimeTranscriptPayload dict (matches arena.runtime.payloads schema)
_BASE_TRANSCRIPT = {
    "schema_version": 1,
    "match_id": MATCH_ID,
    "game_id": GAME_ID,
    "lifecycle": "finished",
    "players": [],
    "events": [],
    "abort": None,
    "match_transcript": None,
}

_ABORTED_TRANSCRIPT = {
    **_BASE_TRANSCRIPT,
    "lifecycle": "aborted",
    "abort": {
        "reason": "peer_disconnected",
        "message": "test abort",
        "cause_type": None,
        "cause_message": None,
    },
}


def make_obs_envelope(seat: int = 0, turn_index: int = 0) -> ObservationRequestEnvelope:
    obs_payload = {
        "game_id": GAME_ID,
        "schema_version": 1,
        "seat": seat,
        "observation": {"board": [], "current_seat": seat},
    }
    body = ObservationRequestBody.model_validate({
        "observation_request": obs_payload,
        "deadline_ms": 30000,
    })
    return ObservationRequestEnvelope(
        schema_version=1,
        match_id=MATCH_ID,
        seat=seat,
        payload=body,
    )


def make_match_state_envelope(lifecycle: str = "running") -> MatchStateEnvelope:
    body = MatchStateBody(lifecycle=lifecycle, turn_count=0)
    return MatchStateEnvelope(schema_version=1, match_id=MATCH_ID, payload=body)


def make_turn_committed_envelope() -> TurnCommittedEnvelope:
    body = TurnCommittedBody(
        turn_record={"turn_index": 0, "seat": 0},
        post_snapshot={"schema_version": 1, "game_id": GAME_ID},
        events=[],
    )
    return TurnCommittedEnvelope(schema_version=1, match_id=MATCH_ID, payload=body)


def make_match_finished_envelope(winner_seat: int = 0) -> MatchFinishedEnvelope:
    body = MatchFinishedBody.model_validate({
        "result": {"kind": "win", "winner_seat": winner_seat},
        "transcript": _BASE_TRANSCRIPT,
    })
    return MatchFinishedEnvelope(schema_version=1, match_id=MATCH_ID, payload=body)


def make_match_aborted_envelope(reason: str = "peer_disconnected") -> MatchAbortedEnvelope:
    abort_dict = {
        "reason": reason,
        "message": "test abort",
        "cause_type": None,
        "cause_message": None,
    }
    transcript = {**_BASE_TRANSCRIPT, "lifecycle": "aborted", "abort": abort_dict}
    body = MatchAbortedBody.model_validate({
        "abort": abort_dict,
        "transcript": transcript,
    })
    return MatchAbortedEnvelope(schema_version=1, match_id=MATCH_ID, payload=body)
