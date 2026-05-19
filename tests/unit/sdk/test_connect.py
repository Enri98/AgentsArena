"""Unit tests for the connect() function and error classes."""
from __future__ import annotations

import asyncio

import pytest

from arena.sdk import _run_session, connect
from arena.sdk.errors import (
    ActionRejectedError,
    HandshakeError,
    HeartbeatTimeoutError,
    MalformedEnvelopeError,
    MatchAbortedError,
    MatchNotFoundError,
    ProtocolError,
    RateLimitedError,
    SchemaVersionError,
    SdkError,
    SeatTakenError,
    ServerError,
    UnauthorizedError,
    close_code_to_error,
)

# ---------------------------------------------------------------------------
# Error class hierarchy tests
# ---------------------------------------------------------------------------


def test_sdk_error_is_base() -> None:
    """SdkError is the root of all SDK exceptions."""
    assert issubclass(SdkError, Exception)


def test_protocol_error_is_sdk_error() -> None:
    assert issubclass(ProtocolError, SdkError)


def test_schema_version_error_is_protocol_error() -> None:
    assert issubclass(SchemaVersionError, ProtocolError)


def test_unauthorized_error_is_protocol_error() -> None:
    assert issubclass(UnauthorizedError, ProtocolError)


def test_match_not_found_error_is_protocol_error() -> None:
    assert issubclass(MatchNotFoundError, ProtocolError)


def test_seat_taken_error_is_protocol_error() -> None:
    assert issubclass(SeatTakenError, ProtocolError)


def test_heartbeat_timeout_error_is_protocol_error() -> None:
    assert issubclass(HeartbeatTimeoutError, ProtocolError)


def test_malformed_envelope_error_is_protocol_error() -> None:
    assert issubclass(MalformedEnvelopeError, ProtocolError)


def test_rate_limited_error_is_protocol_error() -> None:
    assert issubclass(RateLimitedError, ProtocolError)


def test_server_error_is_protocol_error() -> None:
    assert issubclass(ServerError, ProtocolError)


def test_match_aborted_error_is_sdk_error() -> None:
    assert issubclass(MatchAbortedError, SdkError)


def test_action_rejected_error_is_sdk_error() -> None:
    assert issubclass(ActionRejectedError, SdkError)


def test_handshake_error_is_sdk_error() -> None:
    assert issubclass(HandshakeError, SdkError)


# ---------------------------------------------------------------------------
# ProtocolError construction
# ---------------------------------------------------------------------------


def test_protocol_error_stores_code_and_reason() -> None:
    err = ProtocolError(4404, "not found")
    assert err.code == 4404
    assert err.reason == "not found"
    assert "4404" in str(err)
    assert "not found" in str(err)


def test_match_aborted_error_stores_abort_and_transcript() -> None:
    err = MatchAbortedError("abort-body", "transcript")
    assert err.abort_body == "abort-body"
    assert err.transcript == "transcript"


def test_action_rejected_error_stores_payload_and_retries() -> None:
    err = ActionRejectedError("error-payload", 2)
    assert err.error_payload == "error-payload"
    assert err.retries_remaining == 2


# ---------------------------------------------------------------------------
# close_code_to_error mapping tests
# ---------------------------------------------------------------------------


def test_close_code_4400_returns_schema_version_error() -> None:
    err = close_code_to_error(4400, "bad version")
    assert isinstance(err, SchemaVersionError)
    assert err.code == 4400


def test_close_code_4409_returns_seat_taken_error() -> None:
    err = close_code_to_error(4409, "seat taken")
    assert isinstance(err, SeatTakenError)
    assert err.code == 4409


def test_close_code_4410_returns_match_not_found_error() -> None:
    err = close_code_to_error(4410, "match not found")
    assert isinstance(err, MatchNotFoundError)
    assert err.code == 4410


def test_close_code_4408_returns_heartbeat_timeout_error() -> None:
    err = close_code_to_error(4408, "pong timeout")
    assert isinstance(err, HeartbeatTimeoutError)


def test_close_code_4401_returns_unauthorized_error() -> None:
    err = close_code_to_error(4401, "unauthorized")
    assert isinstance(err, UnauthorizedError)


def test_close_code_4422_returns_malformed_envelope_error() -> None:
    err = close_code_to_error(4422, "bad envelope")
    assert isinstance(err, MalformedEnvelopeError)


def test_close_code_4429_returns_rate_limited_error() -> None:
    err = close_code_to_error(4429, "rate limited")
    assert isinstance(err, RateLimitedError)


def test_close_code_4500_returns_server_error() -> None:
    err = close_code_to_error(4500, "internal error")
    assert isinstance(err, ServerError)


def test_close_code_unknown_returns_protocol_error() -> None:
    err = close_code_to_error(9999, "unknown")
    assert type(err) is ProtocolError
    assert err.code == 9999


def test_close_code_to_error_returns_protocol_error_subclass() -> None:
    """All return values are ProtocolError instances."""
    codes = [4400, 4401, 4408, 4409, 4410, 4422, 4429, 4500, 1001]
    for code in codes:
        err = close_code_to_error(code, "reason")
        assert isinstance(err, ProtocolError), f"code {code} did not produce ProtocolError"


# ---------------------------------------------------------------------------
# connect() smoke tests (verify it's an async function)
# ---------------------------------------------------------------------------


def test_connect_is_async_function() -> None:
    """connect() must be an async function."""
    assert asyncio.iscoroutinefunction(connect)


def test_run_session_is_async_function() -> None:
    """_run_session() must be an async function."""
    assert asyncio.iscoroutinefunction(_run_session)


@pytest.mark.anyio
async def test_run_session_via_local_session_smoke() -> None:
    """connect() callback form works end-to-end with LocalSession via _run_session."""
    from arena.sdk.testing import LocalSession
    from tests.unit.sdk.conftest import (
        GAME_ID,
        MATCH_ID,
        make_match_finished_envelope,
        make_obs_envelope,
    )

    script = [
        make_obs_envelope(seat=0),
        make_match_finished_envelope(winner_seat=0),
    ]
    session = LocalSession(
        match_id=MATCH_ID,
        game_id=GAME_ID,
        seat=0,
        server_script=script,
    )
    result, transcript = await _run_session(session, lambda obs: {"column": 0})
    assert result["kind"] == "win"
    assert result["winner_seat"] == 0
