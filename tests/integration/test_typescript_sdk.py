"""The TypeScript SDK (sdk-ts/) against the real server (Phase 42 acceptance).

A TypeScript client completes a match, both seats, and a TypeScript spectator
renders it; for a sequential game and for a simultaneous one. Runs the
TypeScript sources directly with Node's type stripping (Node >= 22.18 or 23.6);
skipped when no such Node is available.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from tests.integration.conftest import serve

SDK = Path(__file__).resolve().parents[2] / "sdk-ts"


def _node() -> str | None:
    node = shutil.which("node")
    if node is None:
        return None
    version = subprocess.run([node, "--version"], capture_output=True, text=True).stdout
    match = re.match(r"v(\d+)\.(\d+)", version.strip())
    if not match:
        return None
    major, minor = int(match[1]), int(match[2])
    if major > 23 or (major == 23 and minor >= 6) or (major == 22 and minor >= 18):
        return node
    return None


NODE = _node()
pytestmark = pytest.mark.skipif(NODE is None, reason="needs Node with TypeScript type stripping")


@pytest.mark.parametrize(
    ("game_id", "turn_kind", "pick"),
    [("tictactoe", "seat", "first"), ("pig", "chance", "last"), ("rps", "round", "first")],
)
def test_the_typescript_sdk_plays_and_watches_a_match(
    game_id: str, turn_kind: str, pick: str
) -> None:
    app = create_app(rate_limiter=RateLimiter.unlimited())
    with serve(app) as server:
        completed = subprocess.run(
            [NODE, "examples/play_match.ts", server.http_base_url, game_id, pick],
            cwd=SDK,
            capture_output=True,
            text=True,
            timeout=90,
        )
    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout.strip().splitlines()[-1])
    assert summary["lifecycle"] == ["finished", "finished"]
    assert summary["spectator_lifecycle"] == "finished"
    assert summary["turns"] > 0
    assert len(summary["spectator_lines"]) == summary["turns"]
    assert any(f" {turn_kind} " in line for line in summary["spectator_lines"]), summary
    assert summary["public_transcript_turns"] == summary["turns"]
