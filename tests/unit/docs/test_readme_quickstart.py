"""Test-backed examples for the README quickstart flow."""

from __future__ import annotations

import json
from dataclasses import dataclass

from arena.core.results import Win
from arena.games import build_default_registry
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    Connect4Observation,
    DropDisc,
)
from arena.match import (
    apply_match_action,
    dump_match_transcript,
    run_local_match,
    start_match,
    validate_match_transcript,
)


def test_readme_quickstart_flow_matches_the_public_connect4_api() -> None:
    registry = build_default_registry()

    definition = registry.get(CONNECT4_GAME_ID)
    config = Connect4Config()

    state = definition.rules_engine.initial_state(config)
    legal_actions = definition.rules_engine.legal_actions(state, state.current_seat)

    assert legal_actions == tuple(
        DropDisc(column=column) for column in range(config.columns)
    )

    move = legal_actions[0]
    transition = definition.rules_engine.apply_action(state, state.current_seat, move)
    next_state = transition.state

    assert next_state.current_seat == 1
    assert next_state.board[-1][0] == 1

    state_payload = definition.serializer.dump_state(next_state)
    rehydrated_state = definition.serializer.load_state(state_payload)
    assert rehydrated_state == next_state

    config_payload = definition.serializer.dump_config(config)
    rehydrated_config = definition.serializer.load_config(config_payload)
    assert rehydrated_config == config


def test_readme_local_match_flow_matches_the_public_match_api() -> None:
    registry = build_default_registry()

    definition = registry.get(CONNECT4_GAME_ID)
    config = Connect4Config()

    match = start_match(definition, config)
    seat = match.rules_engine.current_seat(match.state)
    next_match = apply_match_action(match, seat, DropDisc(column=0))

    assert next_match is not match
    assert match.turns == ()
    assert len(next_match.turns) == 1
    assert next_match.turns[0].seat == seat
    assert next_match.turns[0].action == DropDisc(column=0)
    assert next_match.turns[0].post_snapshot.game_id == CONNECT4_GAME_ID
    assert next_match.turns[0].post_state == next_match.state


def test_readme_transcript_flow_matches_the_public_match_api() -> None:
    registry = build_default_registry()

    definition = registry.get(CONNECT4_GAME_ID)
    match = start_match(definition, Connect4Config(rows=4, columns=4, connect_length=4))

    for column in (0, 1, 0, 1, 0, 1, 0):
        match = apply_match_action(
            match,
            match.rules_engine.current_seat(match.state),
            DropDisc(column=column),
        )

    payload = dump_match_transcript(match)
    loaded = validate_match_transcript(definition, payload)

    assert json.dumps(payload)
    assert payload["game_id"] == CONNECT4_GAME_ID
    assert loaded.latest_state == match.state
    assert loaded.turns[-1].result == Win(seat=0)


@dataclass
class ScriptedPolicy:
    actions: tuple[DropDisc, ...]
    index: int = 0

    def select_action(self, observation: Connect4Observation) -> DropDisc:
        action = self.actions[self.index]
        self.index += 1
        assert action in observation.legal_actions
        return action


def test_readme_policy_flow_matches_the_public_match_api() -> None:
    registry = build_default_registry()

    definition = registry.get(CONNECT4_GAME_ID)
    match = start_match(definition, Connect4Config(rows=4, columns=4, connect_length=4))

    final_match = run_local_match(
        match,
        {
            0: ScriptedPolicy(
                actions=(
                    DropDisc(column=0),
                    DropDisc(column=0),
                    DropDisc(column=0),
                    DropDisc(column=0),
                )
            ),
            1: ScriptedPolicy(
                actions=(
                    DropDisc(column=1),
                    DropDisc(column=1),
                    DropDisc(column=1),
                )
            ),
        },
    )

    assert final_match.rules_engine.is_terminal(final_match.state)
    assert final_match.rules_engine.result(final_match.state) == Win(seat=0)
    assert [turn.seat for turn in final_match.turns] == [0, 1, 0, 1, 0, 1, 0]
