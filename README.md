# AgentsArena

AgentsArena is a Python 3.11 library for pure, turn-based game simulation.

Current scope:
- simulation package only
- sequential, deterministic, perfect-information games
- typed domain objects, registry, rules, serializers, and tests
- first concrete game: Connect 4

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

The public path stays intentionally small:
- `build_default_registry()` returns a registry preloaded with the built-in games
- `register_builtin_games(...)` adds the built-in games to an existing registry
- `definition.rules_engine` creates state, lists legal actions, and applies moves
- `definition.serializer` converts config and state snapshots at the boundary
