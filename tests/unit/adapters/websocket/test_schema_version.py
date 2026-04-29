"""Schema version enforcement: mismatched version raises SchemaVersionMismatch."""

from __future__ import annotations

import json

import pytest

from arena.adapters.websocket import WIRE_SCHEMA_VERSION, SchemaVersionMismatch, loads


def test_unknown_schema_version_raises_schema_version_mismatch() -> None:
    msg = json.dumps(
        {
            "type": "ping",
            "schema_version": 2,
            "match_id": "abc",
            "payload": {"nonce": "x"},
        }
    )
    with pytest.raises(SchemaVersionMismatch) as exc_info:
        loads(msg)

    assert exc_info.value.received == 2
    assert exc_info.value.expected == WIRE_SCHEMA_VERSION


def test_correct_schema_version_does_not_raise() -> None:
    msg = json.dumps(
        {
            "type": "ping",
            "schema_version": WIRE_SCHEMA_VERSION,
            "match_id": "abc",
            "payload": {"nonce": "x"},
        }
    )
    envelope = loads(msg)
    assert envelope.schema_version == WIRE_SCHEMA_VERSION
