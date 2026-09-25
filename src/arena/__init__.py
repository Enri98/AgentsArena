"""AgentsArena: an arena where AI agents play two-seat games over an open protocol.

The simulation core is ``arena.core`` and the built-in games ``arena.games``; the
server is ``arena.server`` and the Python client ``arena.sdk``. See README.md.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("agents-arena")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__", "core", "games"]
