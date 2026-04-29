"""Pytest fixtures for integration tests against a real uvicorn server.

The server runs in a background thread so that the test's asyncio event loop is
independent.  We use Server.should_exit to request shutdown and join the thread
to ensure the socket is released before the next test module starts.

Race note: ephemeral port selection is inherently racy on Windows (SO_REUSEADDR
is not the default).  The probability is low in practice; CI mitigation is to
retry at the test level if needed, but this has not been needed in practice.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

import pytest
import uvicorn

from arena.server.app import create_app


@dataclass(frozen=True)
class RunningServer:
    http_base_url: str
    ws_base_url: str


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def running_server() -> RunningServer:  # type: ignore[return]
    port = _free_port()
    app = create_app()
    # websockets-sansio avoids a cancellation bug in the legacy websockets_impl
    # where cancelling a pending receive_text() task corrupts the ASGI receive
    # state, causing the next receive_text() call from run_match to see a stale
    # disconnect event.  The sansio implementation handles task cancellation
    # correctly.  Also disable uvicorn's keepalive pings to avoid interference.
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        ws="websockets-sansio",
        ws_ping_interval=None,
    )
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10.0
    while not server.started:
        if time.monotonic() > deadline:
            server.should_exit = True
            thread.join(timeout=5)
            raise RuntimeError(f"uvicorn server did not start within 10 s on port {port}")
        time.sleep(0.05)

    yield RunningServer(
        http_base_url=f"http://127.0.0.1:{port}",
        ws_base_url=f"ws://127.0.0.1:{port}",
    )

    server.should_exit = True
    thread.join(timeout=10)
