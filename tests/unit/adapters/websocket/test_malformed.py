"""Rejection of malformed or unsupported input to loads()."""

from __future__ import annotations

import json

import pytest

from arena.adapters.websocket import UnknownMessageType, WireDecodeError, loads


def test_binary_input_raises_wire_decode_error() -> None:
    with pytest.raises(WireDecodeError, match="Binary input"):
        loads(b'{"type": "ping", "schema_version": 1, "payload": {"nonce": "x"}}')


def test_invalid_json_raises_wire_decode_error() -> None:
    with pytest.raises(WireDecodeError, match="Invalid JSON"):
        loads("not json at all {{{")


def test_missing_type_field_raises_wire_decode_error() -> None:
    msg = json.dumps({"schema_version": 1, "payload": {"nonce": "x"}})
    with pytest.raises(WireDecodeError, match="missing required field 'type'"):
        loads(msg)


def test_unknown_type_raises_unknown_message_type() -> None:
    msg = json.dumps(
        {
            "type": "not_a_real_type",
            "schema_version": 1,
            "payload": {},
        }
    )
    with pytest.raises(UnknownMessageType) as exc_info:
        loads(msg)

    assert exc_info.value.message_type == "not_a_real_type"


def test_missing_required_payload_field_raises_wire_decode_error() -> None:
    # ping requires nonce; omit it
    msg = json.dumps({"type": "ping", "schema_version": 1, "payload": {}})
    with pytest.raises(WireDecodeError):
        loads(msg)


def test_json_array_raises_wire_decode_error() -> None:
    with pytest.raises(WireDecodeError, match="JSON object"):
        loads("[1, 2, 3]")
