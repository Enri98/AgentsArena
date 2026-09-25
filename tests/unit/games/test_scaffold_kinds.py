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
from arena.games.scaffold._cli import KINDS, _pascal, _render_files, main
from arena.match import (
    apply_match_action,
    apply_match_chance,
    apply_match_joint_action,
    dump_match_transcript,
    start_match,
    start_replay_match,
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
    """Indistinguishability over whole matches: the same moves under two deals
    that differ only in numbers a viewer may not see must look identical to it,
    in every transcript turn and every observation, until the showdown. Nothing
    here names an event or a field, so a leak added anywhere is caught."""

    generate("hidden", "gen_hidden")
    game = importlib.import_module("arena.games.gen_hidden")
    deal_type = importlib.import_module("arena.games.gen_hidden.outcomes").GenHiddenDeal
    definition = _definition("gen_hidden")
    engine = definition.rules_engine
    serializer = definition.serializer

    def views(deal: tuple[int, int], choices: tuple[str, ...], viewer: int | None) -> tuple:
        match = start_replay_match(definition, definition.config_type())
        match = apply_match_chance(match, deal_type(secrets=deal))
        observations = []
        for seat, choice in enumerate(choices):
            if viewer is not None:
                observed = engine.observation(match.state, viewer)
                observations.append(serializer.dump_observation(observed))
            match = apply_match_action(match, seat, game.GenHiddenAction(choice=choice))
        turns = dump_match_transcript_for_viewer(match, viewer)["turns"]
        return turns, observations

    for choices in (("fold",), ("keep", "fold"), ("keep", "keep")):
        # The showdown (both keep) shows both numbers: compare the turns before it.
        compared = len(choices) if "fold" in choices else len(choices) - 1
        for viewer, other_deal in ((0, (3, 5)), (1, (6, 8)), (None, (6, 5))):
            turns_a, obs_a = views((3, 8), choices, viewer)
            turns_b, obs_b = views(other_deal, choices, viewer)
            # Turn 0 is the deal; turn i + 1 is choice i.
            assert turns_a[: compared + 1] == turns_b[: compared + 1], (choices, viewer)
            assert obs_a == obs_b, (choices, viewer)


@pytest.mark.parametrize("kind", WORKING_KINDS)
def test_the_generated_adapters_work(generate, kind: str) -> None:
    name = f"gen_{kind}"
    generate(kind, name)
    cli = importlib.import_module(f"arena.cli.games.{name}")
    ollama = importlib.import_module(f"arena.agents.ollama.{name}")
    importlib.import_module(f"arena.mcp.games.{name}")
    game = importlib.import_module(f"arena.games.{name}")
    choices = game.CHOICES
    definition = getattr(game, f"{_pascal(name)}GameDefinition")
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

    builder = ollama.__dict__[f"{_pascal(name)}PromptBuilder"]()
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


def _checkout(tmp_path: Path) -> Path:
    """The parts of a checkout the scaffold edits: the real games/__init__.py,
    and adapter packages holding one framework module each."""

    games = tmp_path / "src" / "arena" / "games"
    games.mkdir(parents=True)
    source = REPO_ROOT / "src" / "arena" / "games" / "__init__.py"
    (games / "__init__.py").write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (games / "scaffold").mkdir()
    for parts in (("cli", "games"), ("agents", "ollama"), ("mcp", "games")):
        package = tmp_path.joinpath("src", "arena", *parts)
        package.mkdir(parents=True, exist_ok=True)
        (package / "_registry.py").write_text("", encoding="utf-8")
    (tmp_path / "src" / "arena" / "agents" / "ollama" / "agent.py").write_text("", "utf-8")
    return tmp_path


@pytest.mark.parametrize("kind", WORKING_KINDS)
def test_the_scaffold_writes_a_working_kind_into_a_checkout(
    tmp_path: Path, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path)
    assert main(["--name", "my_game", "--kind", kind, "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert f"Scaffolded a working {kind} game 'my_game'" in out
    assert "from arena.agents.ollama.my_game import MyGamePromptBuilder" in out
    assert (root / "tests" / "contract" / "test_my_game_contract.py").is_file()
    assert (root / "src" / "arena" / "games" / "my_game" / "rules.py").is_file()
    init = (root / "src" / "arena" / "games" / "__init__.py").read_text(encoding="utf-8")
    assert "from arena.games.my_game.definition import register_my_game" in init
    assert "register_my_game(registry)" in init
    # A second run finds the game and refuses, --force or not.
    assert main(["--name", "my_game", "--kind", kind, "--root", str(root), "--force"]) == 2


@pytest.mark.parametrize(
    ("name", "problem"),
    [
        ("class", "Python keyword"),
        ("scaffold", "is not a game"),
        ("agent", "--force would overwrite it"),
        ("Bad", "must match"),
    ],
)
def test_names_that_would_break_the_package_are_refused(
    tmp_path: Path, name: str, problem: str, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _checkout(tmp_path)
    assert main(["--name", name, "--kind", "hidden", "--root", str(root), "--force"]) == 2
    assert problem in capsys.readouterr().err
    init = (root / "src" / "arena" / "games" / "__init__.py").read_text(encoding="utf-8")
    assert f"register_{name}" not in init


def test_a_root_that_is_not_a_checkout_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--name", "demo", "--root", str(tmp_path)]) == 2
    assert "not an AgentsArena source checkout" in capsys.readouterr().err


def test_class_names_are_pascal_case_for_every_kind() -> None:
    assert _pascal("my_game") == "MyGame"
    basic = _render_files("my_game", "basic", REPO_ROOT)
    actions = REPO_ROOT / "src" / "arena" / "games" / "my_game" / "actions.py"
    assert "class MyGameAction(Action):" in basic[actions]
