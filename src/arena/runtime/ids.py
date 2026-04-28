"""Opaque runtime match identifier helpers."""

from __future__ import annotations

from uuid import uuid4

from arena.runtime.exceptions import InvalidMatchId


class MatchId(str):
    """Opaque string identifier for a runtime-owned match session."""

    def __new__(cls, value: str) -> MatchId:
        if not isinstance(value, str):
            raise InvalidMatchId("match id must be a string")

        normalized = value.strip()
        if not normalized:
            raise InvalidMatchId("match id must not be empty")

        return str.__new__(cls, normalized)

    @classmethod
    def generate(cls) -> MatchId:
        """Create a new opaque match id for local runtime use."""

        return cls(f"match_{uuid4().hex}")


def generate_match_id() -> MatchId:
    """Create a new opaque match id for local runtime use."""

    return MatchId.generate()


__all__ = ["MatchId", "generate_match_id"]
