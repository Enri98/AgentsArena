"""Entry point: ``python -m arena.games.scaffold``."""

from __future__ import annotations

import sys

from arena.games.scaffold._cli import main

if __name__ == "__main__":
    sys.exit(main())
