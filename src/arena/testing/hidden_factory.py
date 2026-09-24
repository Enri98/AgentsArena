"""A minimal game with hidden information, for exercising the Phase 38 contract.

The secrets game opens at a chance node that deals each seat a private digit,
then the seats take turns passing until ``max_turns``. It is the smallest game
with both properties Liar's Dice needs — a private share of state, and a chance
outcome that is itself private — and nothing else. Test material, not a
playable game.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from arena.core.actions import Action
from arena.core.chance import ChanceRng
from arena.core.config import BaseGameConfig
from arena.core.events import DomainEvent
from arena.core.exceptions import (
    ChanceResolutionError,
    GameFinished,
    IllegalAction,
    WrongPlayer,
)
from arena.core.game_definition import GameDefinition
from arena.core.observations import Observation
from arena.core.results import Draw
from arena.core.rules_engine import TransitionResult
from arena.core.serializer import JSONMapping
from arena.core.types import Seat

DIGITS = 10


class SecretsConfig(BaseGameConfig):
    max_turns: int = 2


@dataclass(frozen=True)
class SecretsPass(Action):
    """The only move."""


@dataclass(frozen=True)
class SecretsDeal:
    """Chance outcome: one private digit per seat."""

    secrets: tuple[int, int]


@dataclass(frozen=True)
class SecretsObservation(Observation):
    turn: int
    my_secret: int | None


@dataclass(frozen=True)
class SecretsPublicView:
    turn: int
    max_turns: int
    dealt: bool


@dataclass(frozen=True)
class SecretsState:
    turn: int
    max_turns: int
    secrets: tuple[int, int] | None = None


@dataclass(frozen=True)
class SecretsDealt(DomainEvent):
    """Public: the deal happened. Which digit each seat holds is not in it."""


@dataclass(frozen=True)
class SecretReceived(DomainEvent):
    """Private to ``seat``: the digit it was dealt (Phase 38 event visibility)."""

    seat: Seat
    secret: int

    def visible_to(self, viewer: Seat | None) -> bool:
        return viewer == self.seat


@dataclass(frozen=True)
class SecretsPassed(DomainEvent):
    seat: Seat


class SecretsRulesEngine:
    def initial_state(self, config: SecretsConfig) -> SecretsState:
        return SecretsState(turn=0, max_turns=config.max_turns)

    def current_seat(self, state: SecretsState) -> Seat:
        return state.turn % 2

    def legal_actions(self, state: SecretsState, seat: Seat) -> tuple[SecretsPass, ...]:
        if self.is_terminal(state) or self.is_chance_node(state):
            return ()
        return (SecretsPass(),) if seat == self.current_seat(state) else ()

    def validate_action(self, state: SecretsState, seat: Seat, action: SecretsPass) -> None:
        if self.is_terminal(state):
            raise GameFinished("The secrets game is finished.")
        if self.is_chance_node(state):
            raise IllegalAction("The deal is pending.")
        if seat != self.current_seat(state):
            raise WrongPlayer("Not this seat's turn.", details={"seat": seat})
        if not isinstance(action, SecretsPass):
            raise IllegalAction("Unknown secrets-game action.")

    def apply_action(
        self, state: SecretsState, seat: Seat, action: SecretsPass
    ) -> TransitionResult[SecretsState, SecretsPassed, Draw | None]:
        self.validate_action(state, seat, action)
        next_state = replace(state, turn=state.turn + 1)
        return TransitionResult(
            state=next_state, events=(SecretsPassed(seat=seat),), result=self.result(next_state)
        )

    def is_chance_node(self, state: SecretsState) -> bool:
        return state.secrets is None

    def sample_chance(
        self, state: SecretsState, rng: ChanceRng
    ) -> tuple[SecretsDeal, ChanceRng]:
        (a, b), rng = rng.draw_many(DIGITS, 2)
        return SecretsDeal(secrets=(a, b)), rng

    def apply_chance(
        self, state: SecretsState, outcome: SecretsDeal
    ) -> TransitionResult[SecretsState, SecretsDealt, None]:
        if not self.is_chance_node(state):
            raise ChanceResolutionError("The secrets are already dealt.")
        if not isinstance(outcome, SecretsDeal) or not all(
            0 <= digit < DIGITS for digit in outcome.secrets
        ):
            raise ChanceResolutionError("Each secret is a single digit.")
        return TransitionResult(
            state=replace(state, secrets=outcome.secrets),
            events=(
                SecretsDealt(),
                SecretReceived(seat=0, secret=outcome.secrets[0]),
                SecretReceived(seat=1, secret=outcome.secrets[1]),
            ),
        )

    def is_terminal(self, state: SecretsState) -> bool:
        return state.turn >= state.max_turns

    def result(self, state: SecretsState) -> Draw | None:
        return Draw() if self.is_terminal(state) else None

    def observation(self, state: SecretsState, seat: Seat) -> SecretsObservation:
        my_secret = state.secrets[seat] if state.secrets is not None else None
        return SecretsObservation(seat=seat, turn=state.turn, my_secret=my_secret)

    def public_state(self, state: SecretsState) -> SecretsPublicView:
        return SecretsPublicView(
            turn=state.turn, max_turns=state.max_turns, dealt=state.secrets is not None
        )


class SecretsSerializer:
    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        assert isinstance(config, SecretsConfig)
        return {"max_turns": config.max_turns}

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        return SecretsConfig(max_turns=payload["max_turns"])

    def dump_state(self, state: object) -> JSONMapping:
        assert isinstance(state, SecretsState)
        return {
            "turn": state.turn,
            "max_turns": state.max_turns,
            "secrets": list(state.secrets) if state.secrets is not None else None,
        }

    def load_state(self, payload: JSONMapping) -> object:
        secrets = payload["secrets"]
        return SecretsState(
            turn=payload["turn"],
            max_turns=payload["max_turns"],
            secrets=(secrets[0], secrets[1]) if secrets is not None else None,
        )

    def dump_public_state(self, state: object) -> JSONMapping:
        assert isinstance(state, SecretsState)
        return {
            "turn": state.turn,
            "max_turns": state.max_turns,
            "dealt": state.secrets is not None,
        }

    def load_public_state(self, payload: JSONMapping) -> object:
        return SecretsPublicView(
            turn=payload["turn"], max_turns=payload["max_turns"], dealt=payload["dealt"]
        )

    def dump_state_for_seat(self, state: object, seat: Seat) -> JSONMapping:
        assert isinstance(state, SecretsState)
        # Built directly rather than from dump_public_state, so a leak in one
        # view cannot hide behind the other in the contract tests.
        return {
            "turn": state.turn,
            "max_turns": state.max_turns,
            "dealt": state.secrets is not None,
            "seat": seat,
            "my_secret": state.secrets[seat] if state.secrets is not None else None,
        }

    def dump_action(self, action: object) -> JSONMapping:
        assert isinstance(action, SecretsPass)
        return {"type": "pass"}

    def load_action(self, payload: JSONMapping) -> object:
        return SecretsPass()

    def dump_observation(self, observation: object) -> JSONMapping:
        assert isinstance(observation, SecretsObservation)
        return {
            "seat": observation.seat,
            "turn": observation.turn,
            "my_secret": observation.my_secret,
        }

    def load_observation(self, payload: JSONMapping) -> object:
        return SecretsObservation(
            seat=payload["seat"], turn=payload["turn"], my_secret=payload["my_secret"]
        )

    def dump_chance_outcome(self, outcome: object) -> JSONMapping:
        assert isinstance(outcome, SecretsDeal)
        return {"secrets": list(outcome.secrets)}

    def load_chance_outcome(self, payload: JSONMapping) -> object:
        secrets = payload["secrets"]
        return SecretsDeal(secrets=(secrets[0], secrets[1]))

    def dump_chance_outcome_for_seat(self, outcome: object, seat: Seat) -> JSONMapping:
        assert isinstance(outcome, SecretsDeal)
        return {"my_secret": outcome.secrets[seat]}

    def dump_public_chance_outcome(self, outcome: object) -> JSONMapping:
        assert isinstance(outcome, SecretsDeal)
        return {}


def build_secrets_game_definition() -> GameDefinition[
    SecretsConfig, SecretsState, SecretsPass, SecretsObservation, Draw
]:
    return GameDefinition(
        game_id="secrets-game",
        display_name="Secrets Game",
        config_type=SecretsConfig,
        state_type=SecretsState,
        action_type=SecretsPass,
        observation_type=SecretsObservation,
        rules_engine=SecretsRulesEngine(),
        serializer=SecretsSerializer(),
        result_type=Draw,
        has_hidden_information=True,
        has_chance_nodes=True,
    )


@dataclass(frozen=True)
class SecretsContractBundle:
    """A ``GameContractBundle`` for the secrets game, with its private variants."""

    definition: object
    config: SecretsConfig
    initial_state: SecretsState
    near_terminal_state: SecretsState
    terminal_state: SecretsState
    legal_action: SecretsPass
    illegal_action: object
    opening_outcomes: tuple[SecretsDeal, ...]
    private_variants: tuple[object, ...]
    chance_state: SecretsState
    private_outcome_variants: tuple[object, ...]
    revealing_actions: tuple[object, ...] = ()


def build_secrets_contract_bundle() -> SecretsContractBundle:
    from arena.testing.contracts import PrivateVariant

    definition = build_secrets_game_definition()
    config = SecretsConfig(max_turns=2)
    engine = definition.rules_engine
    near_terminal = SecretsState(turn=1, max_turns=2, secrets=(3, 8))
    opening = SecretsState(turn=0, max_turns=2, secrets=(3, 8))
    return SecretsContractBundle(
        definition=definition,
        config=config,
        # The game opens at the deal; opening_outcomes resolve it to this state.
        initial_state=opening,
        near_terminal_state=near_terminal,
        terminal_state=engine.apply_action(near_terminal, 1, SecretsPass()).state,
        legal_action=SecretsPass(),
        illegal_action=object(),
        opening_outcomes=(SecretsDeal(secrets=(3, 8)),),
        # Each seat blind to the other's digit, on its own turn and the other's.
        private_variants=(
            PrivateVariant(opening, replace(opening, secrets=(3, 5)), blind_seat=0),
            PrivateVariant(opening, replace(opening, secrets=(6, 8)), blind_seat=1),
            PrivateVariant(near_terminal, replace(near_terminal, secrets=(3, 5)), blind_seat=0),
            PrivateVariant(near_terminal, replace(near_terminal, secrets=(6, 8)), blind_seat=1),
        ),
        chance_state=engine.initial_state(config),
        private_outcome_variants=(
            PrivateVariant(SecretsDeal((3, 8)), SecretsDeal((3, 5)), blind_seat=0),
            PrivateVariant(SecretsDeal((3, 8)), SecretsDeal((6, 8)), blind_seat=1),
        ),
    )


__all__ = [
    "SecretsConfig",
    "SecretsContractBundle",
    "SecretsDeal",
    "SecretsPass",
    "SecretReceived",
    "SecretsState",
    "build_secrets_contract_bundle",
    "build_secrets_game_definition",
]
