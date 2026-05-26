"""Smoke test for ``python -m arena.games.scaffold --dry-run``."""

from __future__ import annotations

import subprocess
import sys


def test_dry_run_lists_expected_files() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "arena.games.scaffold", "--dry-run", "--name", "demo"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    stdout = result.stdout
    assert "Would create 12 file(s) for game 'demo'" in stdout
    expected = [
        "src/arena/games/demo/__init__.py",
        "src/arena/games/demo/config.py",
        "src/arena/games/demo/state.py",
        "src/arena/games/demo/actions.py",
        "src/arena/games/demo/observation.py",
        "src/arena/games/demo/events.py",
        "src/arena/games/demo/rules.py",
        "src/arena/games/demo/serializer.py",
        "src/arena/games/demo/definition.py",
        "src/arena/cli/games/demo.py",
        "src/arena/agents/ollama/demo.py",
        "src/arena/mcp/games/demo.py",
    ]
    for path in expected:
        assert path in stdout, f"missing {path} in scaffold dry-run output"
    assert "from arena.games.demo.definition import register_demo" in stdout
    assert "register_demo(registry)" in stdout
