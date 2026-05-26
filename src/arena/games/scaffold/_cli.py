"""Implementation of the ``arena.games.scaffold`` CLI.

Stdlib-only. Generates skeleton files for a new game package and its
per-layer adapter modules using string templates. Optionally edits
``src/arena/games/__init__.py`` to wire the new game into the default
registry.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from arena.games.scaffold import _templates

_NAME_PATTERN = re.compile(r"[a-z][a-z0-9_]*")


def _repo_root() -> Path:
    """Return the repository root (the parent of ``src``)."""
    # __file__ lives at <repo>/src/arena/games/scaffold/_cli.py
    return Path(__file__).resolve().parents[4]


def _existing_game_ids(games_dir: Path) -> set[str]:
    """List existing game-package directory names under ``arena.games``."""
    if not games_dir.is_dir():
        return set()
    ids: set[str] = set()
    for entry in games_dir.iterdir():
        if not entry.is_dir():
            continue
        if entry.name.startswith("_") or entry.name == "scaffold":
            continue
        if (entry / "__init__.py").exists():
            ids.add(entry.name)
    return ids


def _render_files(name: str) -> dict[Path, str]:
    """Render every file the scaffold would write, keyed by relative path."""
    pascal = name[:1].upper() + name[1:]
    upper = name.upper()
    ctx = {"name": name, "Name": pascal, "NAME": upper}

    root = _repo_root()
    files: dict[Path, str] = {}
    game_dir = root / "src" / "arena" / "games" / name
    files[game_dir / "__init__.py"] = _templates.GAME_INIT.format(**ctx)
    files[game_dir / "config.py"] = _templates.GAME_CONFIG.format(**ctx)
    files[game_dir / "state.py"] = _templates.GAME_STATE.format(**ctx)
    files[game_dir / "actions.py"] = _templates.GAME_ACTIONS.format(**ctx)
    files[game_dir / "observation.py"] = _templates.GAME_OBSERVATION.format(**ctx)
    files[game_dir / "events.py"] = _templates.GAME_EVENTS.format(**ctx)
    files[game_dir / "rules.py"] = _templates.GAME_RULES.format(**ctx)
    files[game_dir / "serializer.py"] = _templates.GAME_SERIALIZER.format(**ctx)
    files[game_dir / "definition.py"] = _templates.GAME_DEFINITION.format(**ctx)

    files[root / "src" / "arena" / "cli" / "games" / f"{name}.py"] = (
        _templates.CLI_ADAPTER.format(**ctx)
    )
    files[root / "src" / "arena" / "agents" / "ollama" / f"{name}.py"] = (
        _templates.OLLAMA_ADAPTER.format(**ctx)
    )
    files[root / "src" / "arena" / "mcp" / "games" / f"{name}.py"] = (
        _templates.MCP_ADAPTER.format(**ctx)
    )
    return files


def _games_init_edit(name: str, games_init_text: str) -> tuple[str, str]:
    """Return ``(import_line, call_line)`` to be appended to games/__init__.py.

    Idempotent: if the lines are already present we return empty strings to
    signal "no edit needed".
    """
    import_line = f"    from arena.games.{name}.definition import register_{name}"
    call_line = f"    register_{name}(registry)"
    if import_line in games_init_text and call_line in games_init_text:
        return ("", "")
    return (import_line, call_line)


def _apply_games_init_edit(games_init_path: Path, name: str) -> str | None:
    """Edit ``games/__init__.py`` to register the new game. Returns a diff
    note suitable for the printed checklist, or ``None`` if no edit was made.
    """
    text = games_init_path.read_text(encoding="utf-8")
    import_line, call_line = _games_init_edit(name, text)
    if not import_line and not call_line:
        return None

    # Anchor on the last existing register_<other>(registry) call inside the
    # function body of register_builtin_games. We exclude
    # ``register_builtin_games(registry)`` itself (which lives in
    # ``build_default_registry``) so we don't accidentally append into the
    # wrong function.
    call_anchor_re = re.compile(
        r"^(    register_(?!builtin_games\()[a-z0-9_]+\(registry\)\n)",
        re.MULTILINE,
    )
    matches = list(call_anchor_re.finditer(text))
    if not matches:
        raise RuntimeError(
            "Could not find an existing 'register_<game>(registry)' line in "
            f"{games_init_path} to anchor the scaffold edit."
        )
    last = matches[-1]
    insert_at = last.end()
    new_text = text[:insert_at] + call_line + "\n" + text[insert_at:]

    # Now insert the import inside the function body. We find the existing
    # contiguous run of ``from arena.games.<x>.definition import register_<x>``
    # lines, splice the new line in, then re-sort the whole block. That keeps
    # the file ruff/isort-clean regardless of where the new game falls
    # alphabetically.
    import_anchor_re = re.compile(
        r"(?:^    from arena\.games\.[a-z0-9_]+\.definition import register_[a-z0-9_]+\n)+",
        re.MULTILINE,
    )
    block_match = import_anchor_re.search(new_text)
    if block_match is None:
        raise RuntimeError(
            "Could not find an existing 'from arena.games.<x>.definition import "
            f"register_<x>' block in {games_init_path}."
        )
    block_text = block_match.group(0)
    lines = [line for line in block_text.splitlines() if line.strip()]
    lines.append(import_line)
    lines.sort()
    sorted_block = "\n".join(lines) + "\n"
    new_text = new_text[: block_match.start()] + sorted_block + new_text[block_match.end():]

    games_init_path.write_text(new_text, encoding="utf-8")
    return f"{import_line}\n{call_line}"


def _next_steps_checklist(name: str) -> str:
    """Return the printed checklist of follow-ups for the contributor."""
    pascal = name[:1].upper() + name[1:]
    cli_import = f"from arena.cli.games import {name} as _{name}  # noqa: F401"
    ollama_import = f"from arena.agents.ollama.{name} import {pascal}PromptBuilder"
    mcp_import = f"from arena.mcp.games import {name} as _{name}  # noqa: F401"
    return "\n".join(
        [
            "",
            f"Scaffolded game '{name}'. Next steps:",
            "",
            "  1. Wire the adapter modules into their respective package __init__.py:",
            "     - src/arena/cli/games/__init__.py",
            f"         {cli_import}",
            "     - src/arena/agents/ollama/__init__.py",
            f"         {ollama_import}",
            f"         (and list '{pascal}PromptBuilder' in __all__)",
            "     - src/arena/mcp/games/__init__.py",
            f"         {mcp_import}",
            "",
            f"  2. Implement the rules engine in src/arena/games/{name}/rules.py",
            "     (every method currently raises NotImplementedError).",
            "",
            "  3. Fill in the State / Action / Observation / Event dataclasses,",
            "     the Pydantic payload models, and the serializer round-trip.",
            "",
            "  4. Implement the CLI renderers/parser, the Ollama prompt builder,",
            "     and the MCP action_schema in their adapter modules.",
            "",
            f"  5. Add unit tests under tests/unit/games/{name}/ - see existing",
            "     tests/unit/games/nim/ as a template.",
            "",
            "  6. Run ruff and pytest from the venv:",
            "        .\\.venv\\Scripts\\ruff.exe check .",
            "        .\\.venv\\Scripts\\pytest.exe -q",
            "",
            "  See docs/ADDING_A_GAME.md for the full walkthrough.",
            "",
        ]
    )


def _print_dry_run(name: str, files: dict[Path, str], init_edit: tuple[str, str]) -> None:
    """Print the dry-run preview: file list, the planned __init__.py edit,
    and one full example file (events.py — the smallest)."""
    root = _repo_root()
    print(f"[dry-run] Would create {len(files)} file(s) for game '{name}':")
    for path in sorted(files):
        try:
            rel = path.relative_to(root)
        except ValueError:
            rel = path
        print(f"  {rel.as_posix()}")

    import_line, call_line = init_edit
    print("")
    if import_line or call_line:
        print("[dry-run] Would edit src/arena/games/__init__.py to add:")
        if import_line:
            print(import_line)
        if call_line:
            print(call_line)
    else:
        print("[dry-run] src/arena/games/__init__.py already wires this game; "
              "no edit needed.")

    example_path = root / "src" / "arena" / "games" / name / "events.py"
    if example_path in files:
        print("")
        print("[dry-run] Example output (events.py):")
        print("-" * 60)
        print(files[example_path], end="")
        print("-" * 60)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m arena.games.scaffold",
        description="Scaffold the boilerplate for a new AgentsArena game.",
    )
    parser.add_argument(
        "--name",
        required=True,
        help="Lowercase game id (matches /[a-z][a-z0-9_]*/).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Print the file list and one example file; write nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing files. Without it, the scaffold refuses if any target exists.",
    )
    args = parser.parse_args(argv)

    name: str = args.name
    if not _NAME_PATTERN.fullmatch(name):
        sys.stderr.write(
            f"Error: --name {name!r} must match /[a-z][a-z0-9_]*/ "
            "(lowercase Python identifier).\n"
        )
        return 2

    root = _repo_root()
    games_dir = root / "src" / "arena" / "games"
    if name in _existing_game_ids(games_dir):
        sys.stderr.write(
            f"Error: a game package 'arena.games.{name}' already exists. "
            "Choose a different --name (the scaffold refuses to clobber existing games).\n"
        )
        return 2

    files = _render_files(name)

    games_init_path = games_dir / "__init__.py"
    games_init_text = games_init_path.read_text(encoding="utf-8")
    init_edit = _games_init_edit(name, games_init_text)

    if args.dry_run:
        _print_dry_run(name, files, init_edit)
        return 0

    existing = [p for p in files if p.exists()]
    if existing and not args.force:
        sys.stderr.write(
            "Error: the following target files already exist; "
            "pass --force to overwrite:\n"
        )
        for p in existing:
            try:
                rel = p.relative_to(root)
            except ValueError:
                rel = p
            sys.stderr.write(f"  {rel.as_posix()}\n")
        return 2

    for path, contents in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    try:
        edit_diff = _apply_games_init_edit(games_init_path, name)
    except RuntimeError as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 2

    print(f"Wrote {len(files)} file(s) for game '{name}'.")
    if edit_diff:
        print("Updated src/arena/games/__init__.py:")
        print(edit_diff)
    else:
        print("src/arena/games/__init__.py already wires this game; no edit needed.")
    print(_next_steps_checklist(name))
    return 0


__all__: tuple[str, ...] = ("main",)
