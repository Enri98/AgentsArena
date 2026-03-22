"""Tests for shared serializer contracts."""

from __future__ import annotations

import inspect

from arena.core.config import BaseGameConfig
from arena.core.serializer import JSONMapping, Serializer


class ExampleConfig(BaseGameConfig):
    """Trivial config subclass used to verify serializer config typing."""

    rows: int


class DummySerializer:
    """Minimal serializer implementation used to satisfy the shared contract."""

    def dump_config(self, config: BaseGameConfig) -> JSONMapping:
        return {"rows": config.model_dump()["rows"]}

    def load_config(self, payload: JSONMapping) -> BaseGameConfig:
        return ExampleConfig(rows=payload["rows"])

    def dump_state(self, state: object) -> JSONMapping:
        return {"state": "value"}

    def load_state(self, payload: JSONMapping) -> object:
        return payload["state"]

    def dump_action(self, action: object) -> JSONMapping:
        return {"action": "value"}

    def load_action(self, payload: JSONMapping) -> object:
        return payload["action"]

    def dump_observation(self, observation: object) -> JSONMapping:
        return {"observation": "value"}

    def load_observation(self, payload: JSONMapping) -> object:
        return payload["observation"]


def test_serializer_contract_is_importable() -> None:
    assert Serializer.__name__ == "Serializer"


def test_dummy_serializer_satisfies_the_shared_contract() -> None:
    serializer = DummySerializer()

    assert isinstance(serializer, Serializer)


def test_serializer_contract_supports_config_state_action_and_observation_round_trips() -> None:
    serializer = DummySerializer()
    config = ExampleConfig(rows=6)

    assert serializer.dump_config(config) == {"rows": 6}
    assert serializer.load_config({"rows": 6}) == ExampleConfig(rows=6)
    assert serializer.dump_state(object()) == {"state": "value"}
    assert serializer.load_state({"state": "value"}) == "value"
    assert serializer.dump_action(object()) == {"action": "value"}
    assert serializer.load_action({"action": "value"}) == "value"
    assert serializer.dump_observation(object()) == {"observation": "value"}
    assert serializer.load_observation({"observation": "value"}) == "value"


def test_serializer_module_stays_game_agnostic() -> None:
    source = inspect.getsource(__import__("arena.core.serializer", fromlist=["*"]))

    assert "connect4" not in source.lower()
