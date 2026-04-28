"""Pure UI-facing adapters over runtime payload contracts."""

from arena.ui.payloads import (
    UI_ADAPTER_SCHEMA_VERSION,
    UIMatchScreenPayload,
    UIMatchStatusPayload,
    UIMatchTranscriptPayload,
    UIScreenAbortPayload,
    UIScreenPlayerPayload,
    UIScreenResultPayload,
    UIScreenRuntimeEventPayload,
    UIScreenTurnPayload,
    build_match_screen,
    build_match_status,
    build_match_transcript,
)

__all__ = [
    "UI_ADAPTER_SCHEMA_VERSION",
    "UIMatchScreenPayload",
    "UIMatchStatusPayload",
    "UIMatchTranscriptPayload",
    "UIScreenAbortPayload",
    "UIScreenPlayerPayload",
    "UIScreenResultPayload",
    "UIScreenRuntimeEventPayload",
    "UIScreenTurnPayload",
    "build_match_screen",
    "build_match_status",
    "build_match_transcript",
]
