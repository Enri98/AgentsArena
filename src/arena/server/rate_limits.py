"""Protocol §13 rate limits.

Server-layer only.  Lower layers must not import this module: the caps are a
transport concern, exactly like per-turn deadlines and heartbeats.

The caps are hardcoded in v1 (protocol §13) but injectable here so tests can
drive them with small numbers instead of opening eight real sockets.

Exceeding a cap closes the offending WebSocket with ``4429`` or, for match
creation over HTTP, returns ``429 rate_limited`` (protocol §9).
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from typing import Any

# ── Protocol §13 caps (v1, hardcoded) ──────────────────────────────────────

MAX_WS_CONNECTIONS_PER_IP: int = 8
MAX_MATCH_CREATIONS_PER_IP_PER_MIN: int = 5
#: Throttled, not disconnected (see ``reserve_action``). 2 per second, the v1
#: figure, was chosen as "well above any sane agent", but a scripted or fast
#: bot plays two alternating moves in milliseconds; closing it with 4429 then
#: aborted the match as peer_disconnected, blaming a seat that did nothing wrong.
MAX_ACTIONS_PER_MATCH_PER_SEC: int = 10
MAX_CONNECTIONS_PER_MATCH: int = 4
#: Spectators have their own per-match gauge. Counting them against the seats'
#: four slots let two spectators lock a dropped seat out of its own reconnect.
MAX_SPECTATORS_PER_MATCH: int = 16
#: WebSocket opens per source IP per minute, seats and spectators alike. The
#: concurrent cap alone let one client attach and detach in a loop; each attach
#: to a long match costs a welcome of up to megabytes, built on the event loop.
MAX_WS_OPENS_PER_IP_PER_MIN: int = 60
#: GET /matches/{id}/public-transcript per source IP per minute (Phase 40).
MAX_TRANSCRIPT_READS_PER_IP_PER_MIN: int = 30

MATCH_CREATION_WINDOW_S: float = 60.0
OPEN_WINDOW_S: float = 60.0
READ_WINDOW_S: float = 60.0
ACTION_WINDOW_S: float = 1.0

#: Per-IP windows are pruned once this many keys are tracked, so the dicts keyed
#: by client address cannot grow without bound.
_PRUNE_THRESHOLD: int = 4096

#: WebSocket close code for any exceeded cap (protocol §9).
CLOSE_RATE_LIMITED: int = 4429


class RateLimitExceeded(Exception):
    """Raised when a caller exceeds one of the §13 caps.

    ``scope`` is a short stable token naming which cap was hit; it is safe to
    send to the client as a close reason and is used as the log detail.
    """

    def __init__(self, scope: str, message: str) -> None:
        super().__init__(message)
        self.scope = scope
        self.message = message


def client_address(headers: Any, peer_host: str | None, trusted_header: str | None) -> str:
    """The address rate limits bucket a request under.

    The TCP peer, unless the server is configured to trust a header its reverse
    proxy sets (Fly.io's ``Fly-Client-IP``). Behind a proxy the peer is the
    proxy, so every client would share one bucket: eight WebSocket connections
    and five match creations a minute for the whole server. The header is
    trusted as is, so it is only configured when the proxy is the sole way in.
    """

    if trusted_header:
        value = headers.get(trusted_header)
        if value:
            first = value.split(",")[0].strip()
            if first:
                return first[:64]
    return peer_host or "unknown"


def _prune(window: deque[float], now: float, span: float) -> None:
    """Drop timestamps that have fallen out of the trailing window."""

    cutoff = now - span
    while window and window[0] <= cutoff:
        window.popleft()


class RateLimiter:
    """Thread-safe counters for the protocol §13 caps.

    Connection counts are gauges (acquire/release); match creations and actions
    are sliding windows over a trailing interval.
    """

    def __init__(
        self,
        *,
        max_ws_connections_per_ip: int = MAX_WS_CONNECTIONS_PER_IP,
        max_match_creations_per_ip_per_min: int = MAX_MATCH_CREATIONS_PER_IP_PER_MIN,
        max_actions_per_match_per_sec: int = MAX_ACTIONS_PER_MATCH_PER_SEC,
        max_connections_per_match: int = MAX_CONNECTIONS_PER_MATCH,
        max_spectators_per_match: int = MAX_SPECTATORS_PER_MATCH,
        max_ws_opens_per_ip_per_min: int = MAX_WS_OPENS_PER_IP_PER_MIN,
        max_transcript_reads_per_ip_per_min: int = MAX_TRANSCRIPT_READS_PER_IP_PER_MIN,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_ws_per_ip = max_ws_connections_per_ip
        self._max_creations_per_ip = max_match_creations_per_ip_per_min
        self._max_actions_per_match = max_actions_per_match_per_sec
        self._max_conns_per_match = max_connections_per_match
        self._max_spectators_per_match = max_spectators_per_match
        self._max_opens_per_ip = max_ws_opens_per_ip_per_min
        self._max_reads_per_ip = max_transcript_reads_per_ip_per_min
        self._now = time_fn

        self._lock = threading.Lock()
        self._conns_per_ip: dict[str, int] = {}
        self._conns_per_match: dict[str, int] = {}
        self._spectators_per_match: dict[str, int] = {}
        self._creations: dict[str, deque[float]] = {}
        self._opens: dict[str, deque[float]] = {}
        self._reads: dict[str, deque[float]] = {}
        self._actions: dict[str, deque[float]] = {}
        self._prune_at: dict[int, tuple[int, float]] = {}

    @classmethod
    def unlimited(cls) -> "RateLimiter":
        """A limiter with effectively no caps.

        For tests that are not about rate limiting: the whole suite shares one
        client address, so production caps would reject the suite rather than
        an attacker.  Never use this in a served application.
        """

        big = 1_000_000_000
        return cls(
            max_ws_connections_per_ip=big,
            max_match_creations_per_ip_per_min=big,
            max_actions_per_match_per_sec=big,
            max_connections_per_match=big,
            max_spectators_per_match=big,
            max_ws_opens_per_ip_per_min=big,
            max_transcript_reads_per_ip_per_min=big,
        )

    # ── WebSocket connection caps ──────────────────────────────────────────

    def acquire_connection(
        self, *, ip: str, match_id: str, spectator: bool = False
    ) -> None:
        """Reserve one connection slot for ``ip`` on ``match_id``.

        Seats (and their reconnects) share the per-match connection cap;
        spectators have their own per-match cap. Every open, of either kind,
        counts against the per-IP concurrent cap and the per-IP open rate.

        Raises ``RateLimitExceeded`` without reserving a slot if a cap would be
        exceeded. A refused open still counts toward the open rate.
        """

        self.acquire_ip(ip=ip)
        try:
            self.acquire_match_slot(match_id=match_id, spectator=spectator)
        except RateLimitExceeded:
            self.release_ip(ip=ip)
            raise

    def acquire_ip(self, *, ip: str) -> None:
        """Count one open from ``ip`` and take one of its concurrent slots.

        The first step of every WebSocket, before its hello is read.
        """

        now = self._now()
        with self._lock:
            opens = self._window(self._opens, ip, now, OPEN_WINDOW_S)
            if len(opens) >= self._max_opens_per_ip:
                raise RateLimitExceeded(
                    "connection_opens_per_ip",
                    f"Too many connections opened from {ip} "
                    f"(cap {self._max_opens_per_ip} per minute).",
                )
            opens.append(now)

            ip_count = self._conns_per_ip.get(ip, 0)
            if ip_count >= self._max_ws_per_ip:
                raise RateLimitExceeded(
                    "connections_per_ip",
                    f"Too many concurrent connections from {ip} "
                    f"(cap {self._max_ws_per_ip}).",
                )
            self._conns_per_ip[ip] = ip_count + 1

    def release_ip(self, *, ip: str) -> None:
        with self._lock:
            ip_count = self._conns_per_ip.get(ip, 0) - 1
            if ip_count > 0:
                self._conns_per_ip[ip] = ip_count
            else:
                self._conns_per_ip.pop(ip, None)

    def acquire_match_slot(self, *, match_id: str, spectator: bool = False) -> None:
        """Take one of ``match_id``'s seat (or spectator) slots.

        Taken only once a connection's hello is valid. Taken at connect, a
        socket that never said hello held a seat slot for as long as its
        library answered keepalives, and two of them locked a dropped seat out
        of its own reconnect.
        """

        per_match = self._spectators_per_match if spectator else self._conns_per_match
        cap = self._max_spectators_per_match if spectator else self._max_conns_per_match
        with self._lock:
            match_count = per_match.get(match_id, 0)
            if match_count >= cap:
                if spectator:
                    raise RateLimitExceeded(
                        "spectators_per_match",
                        f"Too many spectators of match {match_id} (cap {cap}).",
                    )
                raise RateLimitExceeded(
                    "connections_per_match",
                    f"Too many concurrent connections to match {match_id} "
                    f"(cap {cap}).",
                )

            per_match[match_id] = match_count + 1

    def release_match_slot(self, *, match_id: str, spectator: bool = False) -> None:
        per_match = self._spectators_per_match if spectator else self._conns_per_match
        with self._lock:
            match_count = per_match.get(match_id, 0) - 1
            if match_count > 0:
                per_match[match_id] = match_count
            else:
                per_match.pop(match_id, None)

    def release_connection(
        self, *, ip: str, match_id: str, spectator: bool = False
    ) -> None:
        """Release a slot previously taken by :meth:`acquire_connection`.

        Safe to call more times than acquire; counts never go negative.
        """

        self.release_ip(ip=ip)
        self.release_match_slot(match_id=match_id, spectator=spectator)

    def connection_count(
        self,
        *,
        ip: str | None = None,
        match_id: str | None = None,
        spectator: bool = False,
    ) -> int:
        """Current gauge value, for tests and diagnostics."""

        per_match = self._spectators_per_match if spectator else self._conns_per_match
        with self._lock:
            if ip is not None:
                return self._conns_per_ip.get(ip, 0)
            if match_id is not None:
                return per_match.get(match_id, 0)
            return sum(per_match.values())

    # ── Sliding-window caps ────────────────────────────────────────────────

    def _window(
        self, windows: dict[str, deque[float]], key: str, now: float, span: float
    ) -> deque[float]:
        """``key``'s pruned sliding window. Call with the lock held."""

        threshold, last_scan = self._prune_at.get(id(windows), (_PRUNE_THRESHOLD, now))
        due = len(windows) >= threshold or (
            len(windows) >= _PRUNE_THRESHOLD and now - last_scan >= span
        )
        if due and key not in windows:
            for stale in [k for k, w in windows.items() if not w or w[-1] <= now - span]:
                del windows[stale]
            # Rescan when the survivors have doubled, or a window later: a scan
            # per new key would make every open O(n) under a spray of fresh
            # addresses.
            self._prune_at[id(windows)] = (max(_PRUNE_THRESHOLD, 2 * len(windows)), now)
        window = windows.setdefault(key, deque())
        _prune(window, now, span)
        return window

    def check_match_creation(self, *, ip: str) -> None:
        """Record and bound one match creation from ``ip``."""

        now = self._now()
        with self._lock:
            window = self._window(self._creations, ip, now, MATCH_CREATION_WINDOW_S)
            if len(window) >= self._max_creations_per_ip:
                raise RateLimitExceeded(
                    "match_creations_per_ip",
                    f"Too many matches created from {ip} "
                    f"(cap {self._max_creations_per_ip} per minute).",
                )
            window.append(now)

    def check_transcript_read(self, *, ip: str) -> None:
        """Record and bound one public-transcript read from ``ip`` (Phase 40)."""

        now = self._now()
        with self._lock:
            window = self._window(self._reads, ip, now, READ_WINDOW_S)
            if len(window) >= self._max_reads_per_ip:
                raise RateLimitExceeded(
                    "transcript_reads_per_ip",
                    f"Too many transcript reads from {ip} "
                    f"(cap {self._max_reads_per_ip} per minute).",
                )
            window.append(now)

    def check_action(self, *, match_id: str) -> None:
        """Record and bound one action_response on ``match_id``."""

        now = self._now()
        with self._lock:
            window = self._actions.setdefault(match_id, deque())
            _prune(window, now, ACTION_WINDOW_S)
            if len(window) >= self._max_actions_per_match:
                raise RateLimitExceeded(
                    "actions_per_match",
                    f"Too many actions on match {match_id} "
                    f"(cap {self._max_actions_per_match} per second).",
                )
            window.append(now)

    def reserve_action(self, *, match_id: str) -> float:
        """Reserve the next action slot on ``match_id``; return seconds to wait.

        The cap bounds the work the match loop does per match, and delaying the
        read bounds it just as well as closing the connection, without punishing
        a legitimate fast agent. A flooding seat only slows itself: it is the
        active seat, so its own per-turn deadline keeps running.

        Returns 0.0 when a slot is free now. Otherwise the slot is reserved at
        the moment the window next has room, and the caller waits until then.
        """

        now = self._now()
        with self._lock:
            window = self._actions.setdefault(match_id, deque())
            _prune(window, now, ACTION_WINDOW_S)
            if len(window) < self._max_actions_per_match:
                window.append(now)
                return 0.0
            slot = max(now, window[-self._max_actions_per_match] + ACTION_WINDOW_S)
            window.append(slot)
            return slot - now

    # ── Cleanup ────────────────────────────────────────────────────────────

    def forget_match(self, match_id: str) -> None:
        """Drop all per-match state once a match is evicted."""

        with self._lock:
            self._conns_per_match.pop(match_id, None)
            self._spectators_per_match.pop(match_id, None)
            self._actions.pop(match_id, None)


__all__: Sequence[str] = [
    "ACTION_WINDOW_S",
    "CLOSE_RATE_LIMITED",
    "MATCH_CREATION_WINDOW_S",
    "MAX_ACTIONS_PER_MATCH_PER_SEC",
    "MAX_CONNECTIONS_PER_MATCH",
    "MAX_MATCH_CREATIONS_PER_IP_PER_MIN",
    "MAX_SPECTATORS_PER_MATCH",
    "MAX_TRANSCRIPT_READS_PER_IP_PER_MIN",
    "MAX_WS_CONNECTIONS_PER_IP",
    "MAX_WS_OPENS_PER_IP_PER_MIN",
    "RateLimitExceeded",
    "RateLimiter",
    "client_address",
]
