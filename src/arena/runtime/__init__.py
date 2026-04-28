"""Pure runtime-layer models for local arena session orchestration."""

from arena.runtime.exceptions import (
    ArenaRuntimeError,
    InvalidMatchId,
    InvalidPlayerRecord,
    RuntimeAbortedError,
    RuntimeStateError,
)
from arena.runtime.ids import MatchId, generate_match_id
from arena.runtime.models import (
    AbortMetadata,
    AbortReason,
    MatchAborted,
    MatchCreated,
    MatchFinished,
    MatchStarted,
    PlayerRecord,
    RuntimeEvent,
    RuntimeLifecycle,
    TurnAccepted,
    TurnRequested,
)
from arena.runtime.payloads import (
    RUNTIME_TRANSCRIPT_SCHEMA_VERSION,
    RuntimeAbortPayload,
    RuntimeEventPayload,
    RuntimePlayerPayload,
    RuntimeResultPayload,
    RuntimeSessionStatusPayload,
    RuntimeTranscriptPayload,
    dump_runtime_transcript,
    dump_session_status,
    validate_runtime_transcript,
)
from arena.runtime.session import Arena, MatchSession

__all__ = [
    "AbortMetadata",
    "AbortReason",
    "Arena",
    "ArenaRuntimeError",
    "InvalidMatchId",
    "InvalidPlayerRecord",
    "MatchAborted",
    "MatchCreated",
    "MatchFinished",
    "MatchId",
    "MatchSession",
    "MatchStarted",
    "PlayerRecord",
    "RUNTIME_TRANSCRIPT_SCHEMA_VERSION",
    "RuntimeAbortPayload",
    "RuntimeAbortedError",
    "RuntimeEventPayload",
    "RuntimeEvent",
    "RuntimeLifecycle",
    "RuntimePlayerPayload",
    "RuntimeResultPayload",
    "RuntimeSessionStatusPayload",
    "RuntimeStateError",
    "RuntimeTranscriptPayload",
    "TurnAccepted",
    "TurnRequested",
    "dump_runtime_transcript",
    "dump_session_status",
    "generate_match_id",
    "validate_runtime_transcript",
]
