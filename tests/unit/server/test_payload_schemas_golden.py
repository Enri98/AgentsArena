"""GET /schemas/payloads is byte-stable within a wire version (protocol section 17).

The golden file is the v3 output as first published (main at e28259e). Any
difference is either a bug or a change that needs a schema_version bump. It
caught one: typing ``lifecycle`` as a Literal added an ``enum`` to five schemas.
"""

from __future__ import annotations

import json
from pathlib import Path

from arena.adapters.websocket.codec import WIRE_SCHEMA_VERSION
from arena.server.payload_schemas import get_payload_schemas

GOLDEN = Path(__file__).parent / "golden" / f"payload_schemas_v{WIRE_SCHEMA_VERSION}.json"


def test_published_payload_schemas_match_the_golden_file() -> None:
    assert GOLDEN.exists(), f"a new wire version needs its golden file: {GOLDEN.name}"
    assert get_payload_schemas() == json.loads(GOLDEN.read_text(encoding="utf-8"))
