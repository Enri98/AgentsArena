"""Builds the JSON Schema bundle for GET /schemas/payloads (protocol §17).

Computed once at first call; cached for the process lifetime so the output is
byte-stable for schema_version=1.
"""

from __future__ import annotations

import json
from typing import Any

from arena.adapters.in_process import (
    ActionResponsePayload,
    DomainErrorPayload,
    ObservationRequestPayload,
)
from arena.adapters.websocket.envelope import (
    ActionRejectedEnvelope,
    ActionResponseEnvelope,
    ErrorEnvelope,
    HelloEnvelope,
    MatchAbortedEnvelope,
    MatchFinishedEnvelope,
    MatchStateEnvelope,
    ObservationRequestEnvelope,
    PingEnvelope,
    PongEnvelope,
    TurnCommittedEnvelope,
    WelcomeEnvelope,
)
from arena.runtime.payloads import (
    RuntimeAbortPayload,
    RuntimeEventPayload,
    RuntimePlayerPayload,
    RuntimeSessionStatusPayload,
    RuntimeTranscriptPayload,
)
from arena.server.config import WIRE_SCHEMA_VERSION

_cache: dict[str, Any] | None = None


def _build_envelope_schema() -> dict[str, Any]:
    """Build a merged JSON Schema for all envelope message types."""
    envelope_types = [
        HelloEnvelope,
        WelcomeEnvelope,
        MatchStateEnvelope,
        ObservationRequestEnvelope,
        ActionResponseEnvelope,
        ActionRejectedEnvelope,
        TurnCommittedEnvelope,
        MatchFinishedEnvelope,
        MatchAbortedEnvelope,
        PingEnvelope,
        PongEnvelope,
        ErrorEnvelope,
    ]
    return {
        "oneOf": [cls.model_json_schema() for cls in envelope_types],
        "description": "Discriminated union of all WebSocket envelope message types.",
    }


def get_payload_schemas() -> dict[str, Any]:
    """Return the cached JSON Schema bundle. Computed once per process."""

    global _cache
    if _cache is not None:
        return _cache

    schemas: dict[str, Any] = {
        "ObservationRequestPayload": ObservationRequestPayload.model_json_schema(),
        "ActionResponsePayload": ActionResponsePayload.model_json_schema(),
        "DomainErrorPayload": DomainErrorPayload.model_json_schema(),
        "RuntimeTranscriptPayload": RuntimeTranscriptPayload.model_json_schema(),
        "SessionStatusPayload": RuntimeSessionStatusPayload.model_json_schema(),
        "RuntimeEventPayload": RuntimeEventPayload.model_json_schema(),
        "PlayerRecordPayload": RuntimePlayerPayload.model_json_schema(),
        "AbortMetadataPayload": RuntimeAbortPayload.model_json_schema(),
        "Envelope": _build_envelope_schema(),
    }

    bundle: dict[str, Any] = {
        "schema_version": WIRE_SCHEMA_VERSION,
        "schemas": schemas,
    }

    _cache = bundle
    return _cache


def get_payload_schemas_json() -> str:
    """Return the schema bundle serialised to a stable JSON string."""
    return json.dumps(get_payload_schemas(), sort_keys=True)
