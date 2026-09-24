"""Entry point: python -m arena.server [--host HOST] [--port PORT]."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AgentsArena server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--log-level", default="INFO", help="Logging level (default: INFO).")
    args = parser.parse_args()

    from arena.server.logging_setup import configure_logging

    configure_logging(level=args.log_level)

    import uvicorn

    from arena.server.app import create_app
    from arena.server.config import UVICORN_WS_IMPL

    # The legacy websockets implementation corrupts its receive state when a
    # pending receive_text() is cancelled, which the first-arriving seat's handler
    # does while waiting for its opponent. The seat is then marked disconnected
    # the moment the match starts, and every match aborts peer_disconnected. The
    # test servers always ran sansio, which is why only real deployments broke.
    uvicorn.run(create_app(), host=args.host, port=args.port, ws=UVICORN_WS_IMPL)


if __name__ == "__main__":
    main()
