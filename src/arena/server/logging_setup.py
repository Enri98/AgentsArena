"""Configure structlog for structured JSON logging to stdout.

Call ``configure_logging()`` once at server startup (in ``__main__.py``) before
starting uvicorn.  Lower layers must never call this; logging configuration is
an ``arena.server``-only concern.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog + stdlib logging with a JSON renderer writing to stdout.

    Safe to call multiple times (structlog is idempotent after the first call
    because ``cache_logger_on_first_use=True`` is set only on the first
    ``structlog.configure`` call; subsequent calls are no-ops in practice for
    already-bound loggers, but the configuration itself is reset each time —
    so call once only).
    """
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper(), logging.INFO),
    )
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
