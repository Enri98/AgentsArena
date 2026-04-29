"""Entry point: python -m arena.server [--host HOST] [--port PORT]."""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the AgentsArena server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()

    import uvicorn

    from arena.server.app import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
