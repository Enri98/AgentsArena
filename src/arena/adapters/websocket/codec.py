"""Pure JSON encode/decode helpers for the WebSocket wire protocol.

`dumps` serialises an envelope to a UTF-8 JSON string.
`loads` parses a JSON string into a typed envelope, enforcing schema_version.

Binary input raises WireDecodeError immediately (§3: binary frames must be rejected).
Unknown type raises UnknownMessageType.
JSON parse failure or validation failure raises WireDecodeError.
schema_version != WIRE_SCHEMA_VERSION raises SchemaVersionMismatch.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from arena.adapters.websocket.envelope import WireEnvelope, decode_envelope
from arena.adapters.websocket.errors import SchemaVersionMismatch, WireDecodeError

# Single-sourced from ADAPTER_PAYLOAD_SCHEMA_VERSION; both are pinned to 1 in v1.
# Defined independently here so arena.adapters.websocket does not need to
# import arena.adapters.in_process at the module level for a mere integer.
WIRE_SCHEMA_VERSION = 1


def dumps(envelope: WireEnvelope) -> str:  # type: ignore[valid-type]
    """Serialise a typed envelope to a JSON string."""
    return json.dumps(envelope.model_dump(mode="json"))


def loads(text: str | bytes) -> WireEnvelope:  # type: ignore[valid-type]
    """Parse a JSON string into a typed envelope.

    Raises:
        WireDecodeError: input is bytes, not valid JSON, or fails Pydantic validation.
        UnknownMessageType: the `type` field names an unrecognised message.
        SchemaVersionMismatch: schema_version is not WIRE_SCHEMA_VERSION.
    """
    if isinstance(text, (bytes, bytearray, memoryview)):
        raise WireDecodeError(
            "Binary input is not accepted; WebSocket text frames only (§3)."
        )

    try:
        obj = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WireDecodeError(f"Invalid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise WireDecodeError("Envelope must be a JSON object, not a scalar or array.")

    schema_version = obj.get("schema_version")
    if schema_version is not None and schema_version != WIRE_SCHEMA_VERSION:
        raise SchemaVersionMismatch(received=schema_version, expected=WIRE_SCHEMA_VERSION)

    # decode_envelope raises WireDecodeError / UnknownMessageType as appropriate.
    return decode_envelope(obj)


__all__: Sequence[str] = [
    "WIRE_SCHEMA_VERSION",
    "dumps",
    "loads",
]
