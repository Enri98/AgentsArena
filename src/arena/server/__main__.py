"""Entry point: python -m arena.server [--host HOST] [--port PORT] [...].

The transcript and client-address settings also read ``ARENA_*`` environment
variables, which is how a container deployment configures them (see
docs/DEPLOYMENT.md); a flag wins over its variable.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from collections.abc import Sequence


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    return value if value else None


def _positive_float(text: str) -> float:
    value = float(text)
    if not value > 0:
        raise argparse.ArgumentTypeError(f"must be positive, got {text}")
    return value


def _positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {text}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the AgentsArena server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO).")
    parser.add_argument(
        "--transcript-store",
        default=_env("ARENA_TRANSCRIPT_STORE") or "memory",
        help=(
            "Where ended matches' public transcripts are kept: 'memory' (default; lost "
            "on restart), 'file:DIR', or 'sqlite:PATH'. Env: ARENA_TRANSCRIPT_STORE."
        ),
    )
    parser.add_argument(
        "--transcript-ttl-s",
        type=_positive_float,
        default=_env("ARENA_TRANSCRIPT_TTL_S"),
        help="Seconds a transcript is kept after its match ends (default: 7 days). "
        "Env: ARENA_TRANSCRIPT_TTL_S.",
    )
    parser.add_argument(
        "--transcript-max-entries",
        type=_positive_int,
        default=_env("ARENA_TRANSCRIPT_MAX_ENTRIES"),
        help="Most transcripts kept; the oldest go first (default: 10000). "
        "Env: ARENA_TRANSCRIPT_MAX_ENTRIES.",
    )
    parser.add_argument(
        "--transcript-max-bytes",
        type=_positive_int,
        default=_env("ARENA_TRANSCRIPT_MAX_BYTES"),
        help="Most bytes of transcripts kept (default: 512 MiB on disk, 64 MiB in memory). "
        "Env: ARENA_TRANSCRIPT_MAX_BYTES.",
    )
    parser.add_argument(
        "--transcript-max-record-bytes",
        type=_positive_int,
        default=_env("ARENA_TRANSCRIPT_MAX_RECORD_BYTES"),
        help="Largest single transcript kept (default: 8 MiB on disk, 4 MiB in memory). "
        "Env: ARENA_TRANSCRIPT_MAX_RECORD_BYTES.",
    )
    parser.add_argument(
        "--public-url",
        default=_env("ARENA_PUBLIC_URL"),
        help=(
            "The server's public base URL, e.g. https://arena.example.com. The seat URLs "
            "POST /matches returns are built on it (wss:// for https). Set it behind a "
            "TLS-terminating proxy, or clients are handed ws:// URLs. Env: ARENA_PUBLIC_URL."
        ),
    )
    parser.add_argument(
        "--client-ip-header",
        default=_env("ARENA_CLIENT_IP_HEADER"),
        help=(
            "Request header carrying the client's address, set by a trusted reverse "
            "proxy (Fly.io: Fly-Client-IP). Rate limits are per client address; behind a "
            "proxy every client otherwise shares the proxy's. Only set this when the "
            "server is reachable solely through that proxy: the header is trusted as is. "
            "Env: ARENA_CLIENT_IP_HEADER."
        ),
    )
    return parser


def build_transcript_store(args: argparse.Namespace):  # type: ignore[no-untyped-def]
    """The store the flags describe. Raises ``ValueError`` for a bad spec."""

    from arena.server.transcript_store import (
        DEFAULT_MAX_BYTES,
        DEFAULT_MAX_ENTRIES,
        DEFAULT_MAX_RECORD_BYTES,
        DEFAULT_MEMORY_MAX_BYTES,
        DEFAULT_MEMORY_MAX_RECORD_BYTES,
        DEFAULT_TTL_S,
        RetentionPolicy,
        open_transcript_store,
    )

    in_memory = args.transcript_store == "memory"
    policy = RetentionPolicy(
        ttl_s=float(args.transcript_ttl_s or DEFAULT_TTL_S),
        max_entries=int(args.transcript_max_entries or DEFAULT_MAX_ENTRIES),
        max_bytes=int(
            args.transcript_max_bytes
            or (DEFAULT_MEMORY_MAX_BYTES if in_memory else DEFAULT_MAX_BYTES)
        ),
        max_record_bytes=int(
            args.transcript_max_record_bytes
            or (DEFAULT_MEMORY_MAX_RECORD_BYTES if in_memory else DEFAULT_MAX_RECORD_BYTES)
        ),
    )
    return open_transcript_store(args.transcript_store, policy)


def main(argv: Sequence[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    # Values read from the environment arrive as strings: validate them the
    # same way the flags are.
    try:
        for name, convert in (
            ("transcript_ttl_s", _positive_float),
            ("transcript_max_entries", _positive_int),
            ("transcript_max_bytes", _positive_int),
            ("transcript_max_record_bytes", _positive_int),
        ):
            value = getattr(args, name)
            if isinstance(value, str):
                setattr(args, name, convert(value))
        store = build_transcript_store(args)
    except (ValueError, argparse.ArgumentTypeError) as exc:
        parser.error(str(exc))
    except (OSError, sqlite3.Error) as exc:
        # An unwritable volume (root-owned /data, say): a clear message, not a
        # traceback in a crash loop.
        parser.error(f"cannot open transcript store {args.transcript_store!r}: {exc}")

    from arena.server.logging_setup import configure_logging

    configure_logging(level=args.log_level)

    import structlog
    import uvicorn

    from arena.server.app import create_app
    from arena.server.config import (
        UVICORN_WS_IMPL,
        UVICORN_WS_MAX_SIZE,
        UVICORN_WS_PER_MESSAGE_DEFLATE,
        UVICORN_WS_PING_INTERVAL_S,
        UVICORN_WS_PING_TIMEOUT_S,
    )

    structlog.get_logger("arena.server").info(
        "server_config",
        transcript_store=args.transcript_store,
        transcript_ttl_s=store.policy.ttl_s,
        transcript_max_entries=store.policy.max_entries,
        transcript_max_bytes=store.policy.max_bytes,
        transcript_max_record_bytes=store.policy.max_record_bytes,
        client_ip_header=args.client_ip_header,
        public_url=args.public_url,
    )

    # The legacy websockets implementation corrupts its receive state when a
    # pending receive_text() is cancelled, which the first-arriving seat's handler
    # does while waiting for its opponent. The seat is then marked disconnected
    # the moment the match starts, and every match aborts peer_disconnected. The
    # test servers always ran sansio, which is why only real deployments broke.
    uvicorn.run(
        create_app(
            transcript_store=store,
            client_ip_header=args.client_ip_header,
            public_url=args.public_url,
        ),
        host=args.host,
        port=args.port,
        ws=UVICORN_WS_IMPL,
        ws_ping_interval=UVICORN_WS_PING_INTERVAL_S,
        ws_ping_timeout=UVICORN_WS_PING_TIMEOUT_S,
        ws_max_size=UVICORN_WS_MAX_SIZE,
        ws_per_message_deflate=UVICORN_WS_PER_MESSAGE_DEFLATE,
    )


if __name__ == "__main__":
    main()
