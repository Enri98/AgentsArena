"""Manual game registration and lookup for the simulation package."""

from __future__ import annotations

from collections.abc import Sequence

from arena.core.chance import validate_chance_support
from arena.core.exceptions import DuplicateGameRegistration, UnknownGame
from arena.core.game_definition import GameDefinition
from arena.core.public_view import validate_public_view
from arena.core.simultaneous import validate_simultaneous_support


class GameRegistry:
    """In-memory registry for manually wired game definitions."""

    def __init__(self) -> None:
        self._definitions: dict[str, GameDefinition] = {}

    def register(self, definition: GameDefinition) -> None:
        """Register a game definition by its stable identifier."""

        validate_public_view(definition)
        validate_chance_support(definition)
        validate_simultaneous_support(definition)

        if definition.game_id in self._definitions:
            raise DuplicateGameRegistration(
                f"Game '{definition.game_id}' is already registered.",
                details={"game_id": definition.game_id},
            )

        self._definitions[definition.game_id] = definition

    def get(self, game_id: str) -> GameDefinition:
        """Resolve a registered game definition by stable identifier."""

        try:
            return self._definitions[game_id]
        except KeyError as exc:
            raise UnknownGame(
                f"Unknown game '{game_id}'.",
                details={"game_id": game_id},
            ) from exc

    def list(self) -> tuple[GameDefinition, ...]:
        """Return the registered game definitions in insertion order."""

        return tuple(self._definitions.values())


__all__: Sequence[str] = ["GameRegistry"]
