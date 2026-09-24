"""Pure JSON encode/decode helpers for the WebSocket wire protocol.

`dumps` serialises an envelope to a UTF-8 JSON string.
`loads` parses a JSON string into a typed envelope, enforcing schema_version.

Binary input raises WireDecodeError immediately (§3: binary frames must be rejected).
Unknown type raises UnknownMessageType.
JSON parse failure or validation failure raises WireDecodeError.
A schema_version outside SUPPORTED_WIRE_SCHEMA_VERSIONS raises SchemaVersionMismatch.

Version policy (Phase 37)
-------------------------
The wire emits WIRE_SCHEMA_VERSION but *accepts* every version in
SUPPORTED_WIRE_SCHEMA_VERSIONS. Decode and emit are separate concerns: a server
that can only read what it writes cannot ever migrate without a flag day, and
§7 promises negotiation rather than a hard cutover.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from arena.adapters.websocket.envelope import WireEnvelope, decode_envelope
from arena.adapters.websocket.errors import SchemaVersionMismatch, WireDecodeError

# Defined independently here so arena.adapters.websocket does not need to
# import arena.adapters.in_process at the module level for a mere integer.
#
# Bumped to 2 in Phase 37: transcripts carry chance turns, which have no seat and
# no action. That is a shape change to an existing field (match_finished.transcript,
# match_aborted.transcript) and §7 requires a bump for it.
#
# Bumped to 3 in Phase 38: per-recipient payloads for hidden-information games.
# turn_committed carries each recipient's own view plus public_snapshot, events
# and chance outcomes are filtered per viewer, transcripts declare their view,
# and welcome carries the seat's config view and, on reconnect, its transcript.
#
# Bumped to 4 in Phase 41: simultaneous moves. observation_request can be
# outstanding to several seats at once, and a committed turn can be a joint
# turn (an `actions` map, no single seat or action) in turn_committed and in
# every transcript.
WIRE_SCHEMA_VERSION = 4

#: Versions this build can decode. Older clients' messages are still valid, so
#: there is no reason to refuse to read them.
SUPPORTED_WIRE_SCHEMA_VERSIONS: tuple[int, ...] = (1, 2, 3, 4)


def dumps(envelope: WireEnvelope) -> str:  # type: ignore[valid-type]
    """Serialise a typed envelope to a JSON string."""
    return json.dumps(envelope.model_dump(mode="json"))


def loads(text: str | bytes) -> WireEnvelope:  # type: ignore[valid-type]
    """Parse a JSON string into a typed envelope.

    Raises:
        WireDecodeError: input is bytes, not valid JSON, or fails Pydantic validation.
        UnknownMessageType: the `type` field names an unrecognised message.
        SchemaVersionMismatch: schema_version is outside SUPPORTED_WIRE_SCHEMA_VERSIONS.
    """
    if isinstance(text, (bytes, bytearray, memoryview)):
        raise WireDecodeError(
            "Binary input is not accepted; WebSocket text frames only (§3)."
        )

    try:
        obj = json.loads(text)
    except (ValueError, RecursionError) as exc:
        # ValueError covers JSONDecodeError and an integer too long to convert;
        # RecursionError, nesting too deep to parse. Any of them escaping here
        # used to crash the match driver on one frame.
        raise WireDecodeError(f"Invalid JSON: {type(exc).__name__}") from exc

    if not isinstance(obj, dict):
        raise WireDecodeError("Envelope must be a JSON object, not a scalar or array.")

    schema_version = obj.get("schema_version")
    if schema_version is not None and schema_version not in SUPPORTED_WIRE_SCHEMA_VERSIONS:
        raise SchemaVersionMismatch(received=schema_version, expected=WIRE_SCHEMA_VERSION)

    # decode_envelope raises WireDecodeError / UnknownMessageType as appropriate.
    return decode_envelope(obj)


__all__: Sequence[str] = [
    "SUPPORTED_WIRE_SCHEMA_VERSIONS",
    "WIRE_SCHEMA_VERSION",
    "dumps",
    "loads",
]
