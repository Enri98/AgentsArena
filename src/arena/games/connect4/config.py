"""Validated configuration for the Connect 4 game."""

from __future__ import annotations

from pydantic import Field, model_validator

from arena.core.config import BaseGameConfig


class Connect4Config(BaseGameConfig):
    """Boundary-facing configuration for a Connect 4 board."""

    rows: int = Field(default=6, ge=4)
    columns: int = Field(default=7, ge=4)
    connect_length: int = Field(default=4, ge=2)

    @model_validator(mode="after")
    def validate_connect_length(self) -> "Connect4Config":
        """Ensure the requested connection length can fit on the board."""

        if self.connect_length > max(self.rows, self.columns):
            raise ValueError("connect_length must not exceed the larger board dimension")
        return self


__all__ = ["Connect4Config"]
