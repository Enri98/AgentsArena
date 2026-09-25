"""Core package for shared simulation-layer abstractions."""

from arena.core.actions import Action
from arena.core.chance import ChanceRng, apply_chance, is_chance_node, sample_chance
from arena.core.exceptions import (
    ArenaCoreError,
    ChanceResolutionError,
    ConfigError,
    DuplicateGameRegistration,
    GameFinished,
    IllegalAction,
    IncompleteChanceSupport,
    IncompletePublicView,
    IncompleteSimultaneousSupport,
    InvalidGameConfig,
    RehydrationError,
    RulesError,
    SerializationError,
    UnknownGame,
    WrongPlayer,
)
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.public_view import (
    dump_public_state,
    load_public_state,
    public_state,
    validate_public_view,
)
from arena.core.registry import GameRegistry
from arena.core.rules_engine import RulesEngine, TransitionResult
from arena.core.simultaneous import acting_seats, apply_joint_action, is_joint_node

__all__ = [
    "Action",
    "ArenaCoreError",
    "ConfigError",
    "GameDefinition",
    "GameRegistry",
    "InvalidGameConfig",
    "RulesError",
    "WrongPlayer",
    "IllegalAction",
    "GameFinished",
    "SerializationError",
    "RehydrationError",
    "UnknownGame",
    "DuplicateGameRegistration",
    "Observation",
    "IncompletePublicView",
    "IncompleteChanceSupport",
    "IncompleteSimultaneousSupport",
    "acting_seats",
    "apply_joint_action",
    "is_joint_node",
    "ChanceResolutionError",
    "ChanceRng",
    "apply_chance",
    "is_chance_node",
    "sample_chance",
    "dump_public_state",
    "load_public_state",
    "public_state",
    "validate_public_view",
    "RulesEngine",
    "TransitionResult",
]
