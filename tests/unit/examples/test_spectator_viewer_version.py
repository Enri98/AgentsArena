"""The browser spectator must advertise the wire version the server speaks.

It advertised [1] through Phase 37, so the server — which requires its own
version in the client's list — refused it. Found by adversarial review.
"""

from __future__ import annotations

import re
from pathlib import Path

from arena.adapters.websocket import WIRE_SCHEMA_VERSION

VIEWER = Path(__file__).resolve().parents[3] / "examples" / "spectator" / "index.html"


def test_the_viewer_advertises_the_current_wire_version() -> None:
    match = re.search(r"supported_schema_versions:\s*\[([^\]]*)\]", VIEWER.read_text("utf-8"))
    assert match is not None
    versions = [int(v) for v in match.group(1).split(",") if v.strip()]
    assert WIRE_SCHEMA_VERSION in versions


def test_the_viewer_renders_the_public_snapshot() -> None:
    assert "public_snapshot" in VIEWER.read_text("utf-8")
