# AgentsArena

AgentsArena is a Python 3.11 library for pure, turn-based game simulation.

Current scope:
- simulation package only
- sequential, deterministic, perfect-information games
- typed domain objects, registry, rules, serializers, and tests
- built-in games: Connect 4 and Tic-Tac-Toe

## Quickstart

The intended flow is: register a game, resolve its definition, create initial state, ask for legal actions, apply a move, then serialize and rehydrate the resulting snapshot.

```python
from arena.games import build_default_registry
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    DropDisc,
)

registry = build_default_registry()

definition = registry.get(CONNECT4_GAME_ID)
config = Connect4Config()

state = definition.rules_engine.initial_state(config)
legal_actions = definition.rules_engine.legal_actions(state, state.current_seat)

move = legal_actions[0]
assert move == DropDisc(column=0)

transition = definition.rules_engine.apply_action(state, state.current_seat, move)
next_state = transition.state

state_payload = definition.serializer.dump_state(next_state)
rehydrated_state = definition.serializer.load_state(state_payload)
assert rehydrated_state == next_state

config_payload = definition.serializer.dump_config(config)
rehydrated_config = definition.serializer.load_config(config_payload)
assert rehydrated_config == config
```

For a pure local match, use the dedicated match helpers to keep an immutable turn history:

```python
from arena.games import build_default_registry
from arena.games.connect4 import CONNECT4_GAME_ID, Connect4Config, DropDisc
from arena.match import (
    apply_match_action,
    dump_match_transcript,
    start_match,
    validate_match_transcript,
)

registry = build_default_registry()
definition = registry.get(CONNECT4_GAME_ID)
match = start_match(definition, Connect4Config(rows=4, columns=4, connect_length=4))

for column in (0, 1, 0, 1, 0, 1, 0):
    seat = match.rules_engine.current_seat(match.state)
    match = apply_match_action(match, seat, DropDisc(column=column))

turn = match.turns[-1]
assert turn.action == DropDisc(column=0)
assert turn.post_snapshot.game_id == CONNECT4_GAME_ID

payload = dump_match_transcript(match)
loaded = validate_match_transcript(definition, payload)
assert loaded.latest_state == match.state
assert loaded.turns[-1].result == turn.result
```

For deterministic in-process players, use local policies. Policies receive observations, not mutable internal state:

```python
from dataclasses import dataclass

from arena.games import build_default_registry
from arena.games.connect4 import (
    CONNECT4_GAME_ID,
    Connect4Config,
    Connect4Observation,
    DropDisc,
)
from arena.match import run_local_match, start_match


@dataclass
class ScriptedPolicy:
    actions: tuple[DropDisc, ...]
    index: int = 0

    def select_action(self, observation: Connect4Observation) -> DropDisc:
        action = self.actions[self.index]
        self.index += 1
        assert action in observation.legal_actions
        return action


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
```

For pure local runtime sessions, use `arena.runtime` to add match ids, player metadata, lifecycle, and UI-safe payload envelopes around the existing local match flow:

The runtime envelopes are versioned with a fixed `schema_version` in the payload schema itself.
For the current contract, both status and transcript payloads require `schema_version == 1`.
Any incompatible runtime payload change should bump that value intentionally rather than widening validation.

```python
from dataclasses import dataclass

from arena.games.connect4 import (
    Connect4Config,
    Connect4GameDefinition,
    Connect4Observation,
    DropDisc,
)
from arena.runtime import (
    Arena,
    MatchId,
    PlayerRecord,
    dump_runtime_transcript,
    dump_session_status,
    validate_runtime_transcript,
    validate_session_status,
)
from arena.adapters import TypedPayloadPolicyAdapter


@dataclass
class ScriptedAgent:
    actions: tuple[DropDisc, ...]
    index: int = 0

    def select_action(self, observation: Connect4Observation) -> DropDisc:
        action = self.actions[self.index]
        self.index += 1
        assert action in observation.legal_actions
        return action


arena = Arena(id_factory=lambda: MatchId("runtime-demo"))
session = arena.run_session(
    arena.create_session(
        Connect4GameDefinition,
        Connect4Config(rows=4, columns=4, connect_length=4),
        players=(
            PlayerRecord(player_id="player-0", label="Red", seat=0),
            PlayerRecord(player_id="player-1", label="Yellow", seat=1),
        ),
        policy_bindings={
            0: TypedPayloadPolicyAdapter(
                Connect4GameDefinition,
                ScriptedAgent(
                    actions=(
                        DropDisc(column=0),
                        DropDisc(column=0),
                        DropDisc(column=0),
                        DropDisc(column=0),
                    )
                ),
            ),
            1: TypedPayloadPolicyAdapter(
                Connect4GameDefinition,
                ScriptedAgent(
                    actions=(
                        DropDisc(column=1),
                        DropDisc(column=1),
                        DropDisc(column=1),
                    )
                ),
            ),
        },
    )
)

status = dump_session_status(session)
validated_status = validate_session_status(status)
assert status["schema_version"] == 1
assert validated_status.lifecycle == "finished"
assert status["current_seat"] is None
assert status["latest_snapshot"]["game_id"] == "connect4"

runtime_transcript = dump_runtime_transcript(session)
loaded = validate_runtime_transcript(Connect4GameDefinition, runtime_transcript)
assert runtime_transcript["schema_version"] == 1
assert all(event["event_scope"] == "runtime" for event in runtime_transcript["events"])
assert loaded is not None
assert loaded.latest_state == session.local_match.state
```

The public path stays intentionally small:
- `build_default_registry()` returns a registry preloaded with the built-in games
- `register_builtin_games(...)` adds the built-in games to an existing registry
- `definition.rules_engine` creates state, lists legal actions, and applies moves
- `definition.serializer` converts config and state snapshots at the boundary
- `arena.match` records immutable local match turns and serialized snapshots
- `dump_match_transcript(...)` and `validate_match_transcript(...)` export and replay-check local transcripts
- `run_local_match(...)` drives in-process observation-based policies to terminal state
- `arena.runtime` adds pure in-memory session lifecycle, player metadata, match ids, status payloads, and wrapped runtime transcripts
