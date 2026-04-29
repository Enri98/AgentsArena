"""Forward-compatibility: unknown envelope and body fields are silently dropped."""

from __future__ import annotations

import json

from arena.adapters.websocket import WIRE_SCHEMA_VERSION, loads


def test_unknown_envelope_field_is_dropped() -> None:
    msg = json.dumps(
        {
            "type": "ping",
            "schema_version": WIRE_SCHEMA_VERSION,
            "match_id": "abc",
            "payload": {"nonce": "x"},
            "future_envelope_field": "ignored",
        }
    )
    envelope = loads(msg)
    dumped = envelope.model_dump(mode="json")
    assert "future_envelope_field" not in dumped
    assert dumped["payload"]["nonce"] == "x"


def test_unknown_body_field_on_hello_is_dropped() -> None:
    msg = json.dumps(
        {
            "type": "hello",
            "schema_version": WIRE_SCHEMA_VERSION,
            "match_id": "abc",
            "payload": {
                "client_name": "test",
                "client_version": "0.0.1",
                "supported_schema_versions": [1],
                "requested_seat": 0,
                "future_hello_field": "ignored",
            },
        }
    )
    envelope = loads(msg)
    dumped = envelope.model_dump(mode="json")
    assert "future_hello_field" not in dumped["payload"]
    assert dumped["payload"]["client_name"] == "test"


def test_roundtrip_after_forward_compat_drop() -> None:
    msg = json.dumps(
        {
            "type": "ping",
            "schema_version": WIRE_SCHEMA_VERSION,
            "payload": {"nonce": "round-trip-nonce", "extra": "dropped"},
        }
    )
    from arena.adapters.websocket import dumps

    envelope = loads(msg)
    restored = loads(dumps(envelope))
    assert restored.model_dump(mode="json") == envelope.model_dump(mode="json")
