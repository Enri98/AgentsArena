"""Round-trip tests: every message type must survive dumps -> loads unchanged."""

from __future__ import annotations

from arena.adapters.in_process import (
    ADAPTER_PAYLOAD_SCHEMA_VERSION,
    ActionResponsePayload,
    DomainErrorPayload,
    ObservationRequestPayload,
)
from arena.adapters.websocket import (
    WIRE_SCHEMA_VERSION,
    ActionRejectedBody,
    ActionRejectedEnvelope,
    ActionResponseBody,
    ActionResponseEnvelope,
    ErrorBody,
    ErrorEnvelope,
    HelloBody,
    HelloEnvelope,
    MatchAbortedBody,
    MatchAbortedEnvelope,
    MatchFinishedBody,
    MatchFinishedEnvelope,
    MatchStateBody,
    MatchStateEnvelope,
    ObservationRequestBody,
    ObservationRequestEnvelope,
    PingBody,
    PingEnvelope,
    PlayerInfoBody,
    PongBody,
    PongEnvelope,
    TurnCommittedBody,
    TurnCommittedEnvelope,
    WelcomeBody,
    WelcomeEnvelope,
    dumps,
    loads,
)
from arena.runtime.payloads import RuntimeAbortPayload, RuntimeTranscriptPayload

_MATCH_ID = "test-match-abc123"
_SEAT = 0


def _minimal_transcript() -> RuntimeTranscriptPayload:
    return RuntimeTranscriptPayload(
        match_id=_MATCH_ID,
        game_id="connect4",
        schema_version=1,
        lifecycle="finished",
        players=[],
        events=[],
        abort=None,
        match_transcript=None,
    )


def _minimal_obs_request() -> ObservationRequestPayload:
    return ObservationRequestPayload(
        game_id="connect4",
        schema_version=ADAPTER_PAYLOAD_SCHEMA_VERSION,
        seat=_SEAT,
        observation={"seat": 0, "current_seat": 0, "board": [], "legal_actions": []},
    )


def _roundtrip(envelope):
    text = dumps(envelope)
    restored = loads(text)
    assert restored.model_dump(mode="json") == envelope.model_dump(mode="json")
    return restored


def test_hello_roundtrip() -> None:
    env = HelloEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        seat=_SEAT,
        payload=HelloBody(
            client_name="arena-sdk-python",
            client_version="0.1.0",
            supported_schema_versions=[1],
            requested_seat=_SEAT,
        ),
    )
    _roundtrip(env)


def test_welcome_roundtrip() -> None:
    env = WelcomeEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        seat=_SEAT,
        payload=WelcomeBody(
            match_id=_MATCH_ID,
            game_id="connect4",
            game_schema_version=1,
            seat=_SEAT,
            lifecycle="created",
            schema_version=WIRE_SCHEMA_VERSION,
            negotiated_schema_version=WIRE_SCHEMA_VERSION,
            resume_token="opaque-token",
            per_turn_deadline_ms=30000,
            per_action_retry_budget=3,
            disconnect_grace_ms=30000,
            players=[PlayerInfoBody(player_id="p0", label="alice", seat=0)],
            match_config={"rows": 6, "columns": 7},
        ),
    )
    _roundtrip(env)


def test_match_state_roundtrip() -> None:
    env = MatchStateEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        payload=MatchStateBody(lifecycle="running", current_seat=0, turn_count=0),
    )
    _roundtrip(env)


def test_observation_request_roundtrip() -> None:
    env = ObservationRequestEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        seat=_SEAT,
        payload=ObservationRequestBody(
            observation_request=_minimal_obs_request(),
            deadline_ms=30000,
        ),
    )
    _roundtrip(env)


def test_action_response_roundtrip() -> None:
    env = ActionResponseEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        seat=_SEAT,
        turn_id="550e8400-e29b-41d4-a716-446655440000",
        payload=ActionResponseBody(
            action_response=ActionResponsePayload(
                game_id="connect4",
                schema_version=ADAPTER_PAYLOAD_SCHEMA_VERSION,
                seat=_SEAT,
                action={"column": 3},
            )
        ),
    )
    _roundtrip(env)


def test_action_rejected_roundtrip() -> None:
    env = ActionRejectedEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        seat=_SEAT,
        payload=ActionRejectedBody(
            turn_id="550e8400-e29b-41d4-a716-446655440000",
            error=DomainErrorPayload(code="illegal_action", message="Column is full."),
            retries_remaining=2,
        ),
    )
    _roundtrip(env)


def test_turn_committed_roundtrip() -> None:
    env = TurnCommittedEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        payload=TurnCommittedBody(
            turn_record={"turn_index": 1, "seat": 0, "action": {"column": 3}},
            post_snapshot={"game_id": "connect4", "schema_version": 1, "state": {}},
            events=[],
        ),
    )
    _roundtrip(env)


def test_match_finished_roundtrip() -> None:
    env = MatchFinishedEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        payload=MatchFinishedBody(
            result={"result_type": "win", "winner_seat": 0},
            transcript=_minimal_transcript(),
        ),
    )
    _roundtrip(env)


def test_match_aborted_roundtrip() -> None:
    env = MatchAbortedEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        payload=MatchAbortedBody(
            abort=RuntimeAbortPayload(
                reason="peer_disconnected",
                message="Seat 1 disconnected.",
            ),
            transcript=_minimal_transcript(),
        ),
    )
    _roundtrip(env)


def test_ping_roundtrip() -> None:
    env = PingEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        payload=PingBody(nonce="abc123"),
    )
    _roundtrip(env)


def test_pong_roundtrip() -> None:
    env = PongEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        payload=PongBody(nonce="abc123"),
    )
    _roundtrip(env)


def test_error_roundtrip() -> None:
    env = ErrorEnvelope(
        schema_version=WIRE_SCHEMA_VERSION,
        match_id=_MATCH_ID,
        payload=ErrorBody(code="protocol_violation", message="Unexpected message."),
    )
    _roundtrip(env)
