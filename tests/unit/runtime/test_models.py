"""Tests for runtime value-object validation."""

from __future__ import annotations

import pytest

from arena.runtime import AbortMetadata, AbortReason, InvalidPlayerRecord, PlayerRecord


def test_player_record_rejects_non_string_player_id_and_label() -> None:
    with pytest.raises(InvalidPlayerRecord, match="player_id must be a string"):
        PlayerRecord(player_id=123, seat=0)  # type: ignore[arg-type]

    with pytest.raises(InvalidPlayerRecord, match="label must be a string"):
        PlayerRecord(player_id="player-0", seat=0, label=123)  # type: ignore[arg-type]


def test_abort_metadata_rejects_non_string_fields() -> None:
    with pytest.raises(ValueError, match="abort message must be a string"):
        AbortMetadata(reason=AbortReason.RUNTIME_ERROR, message=123)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="cause_type must be a string"):
        AbortMetadata(
            reason=AbortReason.RUNTIME_ERROR,
            message="failed",
            cause_type=123,  # type: ignore[arg-type]
        )

    with pytest.raises(ValueError, match="cause_message must be a string"):
        AbortMetadata(
            reason=AbortReason.RUNTIME_ERROR,
            message="failed",
            cause_message=123,  # type: ignore[arg-type]
        )
