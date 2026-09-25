"""The scaffold's working kinds (Phase 42): each generates a game that works.

Each kind is rendered into a temporary tree and made importable as
``arena.games.<name>`` (and its adapters under their packages) by extending the
package search paths. The generated code must lint clean, pass its own
generated contract test (the shared contract suite), register, and play whole
matches whose transcripts replay.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import random
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

import arena.agents.ollama
import arena.cli.games
import arena.games
import arena.mcp.games
from arena.agents.ollama._adapters import OLLAMA_GAME_ADAPTERS
from arena.cli.games._registry import CLI_GAME_ADAPTERS
from arena.core.registry import GameRegistry
from arena.core.simultaneous import acting_seats
from arena.games.scaffold._cli import KINDS, _render_files, main
from arena.match import (
    apply_match_action,
    apply_match_joint_action,
    dump_match_transcript,
    start_match,
    validate_match_transcript,
)
from arena.match.transcript import dump_match_transcript_for_viewer
from arena.mcp._adapters import MCP_GAME_ADAPTERS

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKING_KINDS = tuple(kind for kind in KINDS if kind != "basic")

_PACKAGES = (
    (arena.games, "src/arena/games"),
    (arena.cli.games, "src/arena/cli/games"),
    (arena.agents.ollama, "src/arena/agents/ollama"),
    (arena.mcp.games, "src/arena/mcp/games"),
)


class Generated:
    def __init__(self, name: str, root: Path, files: dict[Path, str]) -> None:
        self.name = name
        self.root = root
        self.files = files

    def module(self, suffix: str = "") -> ModuleType:
        return importlib.import_module(f"arena.games.{self.name}{suffix}")

    def contract_tests(self) -> ModuleType:
        path = self.root / "tests" / "contract" / f"test_{self.name}_contract.py"
        spec = importlib.util.spec_from_file_location(f"_generated_{self.name}_contract", path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module


@pytest.fixture
def generate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator:
    names: list[str] = []
    for package, relative in _PACKAGES:
        monkeypatch.setattr(package, "__path__", [*package.__path__, str(tmp_path / relative)])

    def _generate(kind: str, name: str) -> Generated:
        files = _render_files(name, kind, root=tmp_path)
        for path, text in files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        importlib.invalidate_caches()
        names.append(name)
        return Generated(name, tmp_path, files)

    yield _generate

    for name in names:
        for key in [k for k in sys.modules if name in k.split(".")[-1] or f".{name}." in k]:
            del sys.modules[key]
        for registry in (CLI_GAME_ADAPTERS, OLLAMA_GAME_ADAPTERS, MCP_GAME_ADAPTERS):
            registry.pop(name, None)


def _play(definition: object, seed: int) -> object:
    """A whole match between two seats choosing uniformly at random."""

    chooser = random.Random(seed)
    match = start_match(definition, definition.config_type(), seed=seed)
    engine = match.rules_engine
    for _ in range(500):
        if engine.is_terminal(match.state):
            return match
        seats = acting_seats(engine, match.state)
        if len(seats) > 1:
            actions = {s: chooser.choice(engine.legal_actions(match.state, s)) for s in seats}
            match = apply_match_joint_action(match, actions)
        else:
            legal = engine.legal_actions(match.state, seats[0])
            match = apply_match_action(match, seats[0], chooser.choice(legal))
    raise AssertionError("the generated game did not finish in 500 turns")


@pytest.mark.parametrize("kind", WORKING_KINDS)
def test_the_generated_game_passes_its_contract_test(generate, kind: str) -> None:
    generated = generate(kind, f"gen_{kind}")
    tests = generated.contract_tests()
    ran = [name for name in vars(tests) if name.startswith("test_")]
    assert ran
    for name in ran:
        getattr(tests, name)()


@pytest.mark.parametrize("kind", WORKING_KINDS)
def test_the_generated_code_lints_clean(generate, kind: str) -> None:
    # A 20-character id: long names make the longest lines.
    generated = generate(kind, f"a_longer_name_{kind[:6]}")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--config",
            str(REPO_ROOT / "pyproject.toml"),
            # In the temporary tree ruff cannot tell arena is first-party.
            "--config",
            "lint.isort.known-first-party = ['arena']",
            "--output-format",
            "concise",
            str(generated.root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


_CAPABILITY = {
    "chance": "has_chance_nodes",
    "hidden": "has_hidden_information",
    "simultaneous": "has_simultaneous_moves",
}


def _definition(name: str) -> object:
    module = importlib.import_module(f"arena.games.{name}.definition")
    return getattr(module, f"build_{name}_game_definition")()


@pytest.mark.parametrize("kind", WORKING_KINDS)
def test_the_generated_game_registers_and_plays_whole_matches(generate, kind: str) -> None:
    name = f"gen_{kind}"
    generate(kind, name)
    definition = _definition(name)
    GameRegistry().register(definition)  # validates chance, view, simultaneous support
    assert getattr(definition, _CAPABILITY[kind]) is True

    for seed in range(20):
        transcript = dump_match_transcript(_play(definition, seed))
        validate_match_transcript(definition, transcript)
        json.dumps(transcript)  # JSON-safe end to end


def test_the_hidden_game_keeps_each_number_from_the_other_seat(generate) -> None:
    generate("hidden", "gen_hidden")
    definition = _definition("gen_hidden")
    for seed in range(20):
        match = _play(definition, seed)
        secrets = match.state.secrets
        for viewer in (0, 1, None):
            view = dump_match_transcript_for_viewer(match, viewer)
            assert view["view"] == ("public" if viewer is None else "seat")
            deal = view["turns"][0]
            assert deal["kind"] == "chance"
            expected = {} if viewer is None else {"my_secret": secrets[viewer]}
            assert deal["outcome"] == expected
            received = [
                event["payload"]
                for turn in view["turns"]
                for event in turn["events"]
                if event["event_type"].endswith("SecretReceived")
            ]
            assert received == ([] if viewer is None else [{"seat": viewer,
                                                             "secret": secrets[viewer]}])
            states = [turn["post_snapshot"]["state"] for turn in view["turns"]]
            assert all("secrets" not in state for state in states)
            for state in states[:-1]:  # before the end, nobody's number is shown
                assert state["revealed"] is None


@pytest.mark.parametrize("kind", WORKING_KINDS)
def test_the_generated_adapters_work(generate, kind: str) -> None:
    name = f"gen_{kind}"
    generate(kind, name)
    cli = importlib.import_module(f"arena.cli.games.{name}")
    ollama = importlib.import_module(f"arena.agents.ollama.{name}")
    importlib.import_module(f"arena.mcp.games.{name}")
    game = importlib.import_module(f"arena.games.{name}")
    choices = game.CHOICES
    definition = getattr(game, f"{name.title().replace('_', '')}GameDefinition")
    match = start_match(definition, definition.config_type(), seed=7)
    engine = match.rules_engine
    seat = acting_seats(engine, match.state)[0]
    observation = engine.observation(match.state, seat)
    first = observation.legal_actions[0]

    assert name in CLI_GAME_ADAPTERS and name in OLLAMA_GAME_ADAPTERS
    assert MCP_GAME_ADAPTERS[name].action_schema["properties"]["choice"]["enum"] == list(choices)

    assert cli.parse_input(first.choice, observation) == first
    assert cli.parse_input(first.choice[:3].upper(), observation) == first
    assert cli.parse_input("nonsense", observation) is None
    assert "\n" in cli.render_state_plain(definition.serializer.dump_state(match.state))

    builder = ollama.__dict__[f"{name.title().replace('_', '')}PromptBuilder"]()
    messages = builder.build_messages(observation, ("try again",))
    assert messages[0]["role"] == "system" and "try again" in messages[1]["content"]
    reply = json.dumps({"thought": "t", "choice": first.choice.upper()})
    assert builder.parse_response(reply, observation) == first
    assert builder.parse_response('{"choice": "nonsense"}', observation) is None
    assert builder.parse_response("not json", observation) is None
    assert builder.format_spec()["properties"]["choice"]["enum"] == list(choices)

    # A client's action payload is validated at the boundary.
    serializer = definition.serializer
    assert serializer.load_action(serializer.dump_action(first)) == first
    with pytest.raises(ValueError):
        serializer.load_action({"choice": "nonsense"})


@pytest.mark.parametrize("kind", WORKING_KINDS)
def test_dry_run_lists_the_kind_files(kind: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dry-run", "--name", "demo", "--kind", kind]) == 0
    out = capsys.readouterr().out
    assert "src/arena/games/demo/rules.py" in out
    assert "tests/contract/test_demo_contract.py" in out
    has_outcomes = "src/arena/games/demo/outcomes.py" in out
    assert has_outcomes == (kind in ("chance", "hidden"))


def test_an_unknown_kind_is_refused(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        main(["--dry-run", "--name", "demo", "--kind", "quantum"])
