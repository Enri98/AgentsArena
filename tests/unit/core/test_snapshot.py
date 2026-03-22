"""Tests for snapshot envelope models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from arena.core.serializer import SnapshotEnvelope


def test_snapshot_envelope_is_importable() -> None:
    assert SnapshotEnvelope.__name__ == "SnapshotEnvelope"


def test_snapshot_envelope_round_trips_as_json() -> None:
    envelope = SnapshotEnvelope(
        game_id="connect4",
        schema_version=1,
        state={"board": [[0, 0], [0, 0]], "current_seat": 0},
    )

    payload = envelope.model_dump_json()
    round_tripped = SnapshotEnvelope.model_validate_json(payload)

    assert round_tripped == envelope


def test_snapshot_envelope_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        SnapshotEnvelope.model_validate({"game_id": "connect4", "state": {}})


@pytest.mark.parametrize(
    ("payload", "field_name"),
    [
        ({"game_id": "connect4", "schema_version": "1", "state": {}}, "schema_version"),
        ({"game_id": "connect4", "schema_version": 0, "state": {}}, "schema_version"),
        ({"game_id": "connect4", "schema_version": 1, "state": {}, "extra": True}, "extra"),
    ],
)
def test_snapshot_envelope_rejects_malformed_payloads(
    payload: dict[str, object],
    field_name: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        SnapshotEnvelope.model_validate(payload)

    assert field_name in str(exc_info.value)
