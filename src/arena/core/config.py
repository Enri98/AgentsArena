"""Shared Pydantic config models for the simulation core."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class BaseGameConfig(BaseModel):
    """Base class for validated game configuration models."""

    model_config = ConfigDict(extra="forbid", strict=True)


__all__ = ["BaseGameConfig"]
