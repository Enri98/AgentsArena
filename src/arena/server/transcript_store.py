"""Persistence for the public transcripts of ended matches (Phase 40).

A match's public transcript is what a spectator receives in ``match_finished``
or ``match_aborted``. Storing it lets ``GET /matches/{id}/public-transcript``
answer after the WebSocket connections close, after the registry evicts the
match, and, with a durable backend, after a restart.

**Only public transcripts are stored.** Nothing hidden (a Liar's Dice hand)
reaches the store, so no store or read bug can leak one. A caller declares the
audience a body was built for, and a store refuses anything but ``"public"``.
(A perfect-information game's public transcript is labelled ``view: "full"``:
with nothing hidden, the public sees everything.)

Three backends share one contract (``tests/unit/server/test_transcript_store.py``):

* :class:`MemoryTranscriptStore`, the default: outlives connections and
  eviction, not the process;
* :class:`FileTranscriptStore`: one JSON file per match in a directory;
* :class:`SqliteTranscriptStore`: one table in a SQLite file.

Retention is a :class:`RetentionPolicy`: a TTL from the moment the match ended,
plus caps on the number of records and their total size, the oldest dropped
first. Expiry is checked on every read, so an expired record is gone at once
(``404``) whether or not a sweep has run yet. Stores are thread-safe; the server
calls them from worker threads so disk I/O never blocks the event loop.

A durable store belongs to one server process: the file and SQLite backends
are not designed for several servers writing one directory or database.
"""

from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

#: The only audience a stored transcript may have been built for.
PUBLIC_AUDIENCE = "public"

DEFAULT_TTL_S: float = 7 * 86_400.0
DEFAULT_MAX_ENTRIES: int = 10_000
#: Durable backends: bounded so a client playing long matches cannot fill a disk.
DEFAULT_MAX_BYTES: int = 1 << 30
#: The in-memory default shares the process with everything else.
DEFAULT_MEMORY_MAX_BYTES: int = 64 << 20

#: Match ids are ``secrets.token_urlsafe(16)``. Anything else is refused before
#: it reaches a path or a query, so an id cannot traverse out of the directory.
_MATCH_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def is_valid_match_id(match_id: object) -> bool:
    return isinstance(match_id, str) and _MATCH_ID.fullmatch(match_id) is not None


class TranscriptRejected(ValueError):
    """A transcript the store will not keep (not public, too large, bad id)."""


@dataclass(frozen=True)
class RetentionPolicy:
    """How long, and how many, public transcripts are kept.

    ``ttl_s`` counts from the moment the match ended. When a new record would
    exceed ``max_entries`` or ``max_bytes``, the records that ended first are
    dropped. A single transcript larger than ``max_bytes`` is not stored.
    """

    ttl_s: float = DEFAULT_TTL_S
    max_entries: int = DEFAULT_MAX_ENTRIES
    max_bytes: int = DEFAULT_MAX_BYTES

    def __post_init__(self) -> None:
        if not self.ttl_s > 0:
            raise ValueError(f"ttl_s must be positive, got {self.ttl_s!r}.")
        if self.max_entries < 1:
            raise ValueError(f"max_entries must be at least 1, got {self.max_entries!r}.")
        if self.max_bytes < 1:
            raise ValueError(f"max_bytes must be at least 1, got {self.max_bytes!r}.")


@dataclass(frozen=True)
class StoredTranscript:
    """One ended match's public transcript, as UTF-8 JSON bytes."""

    match_id: str
    ended_at: float  # seconds since the epoch: it must survive a restart
    body: bytes


class TranscriptStore(Protocol):
    """Where the public transcripts of ended matches live."""

    policy: RetentionPolicy

    def put(self, match_id: str, body: bytes, *, audience: str) -> StoredTranscript:
        """Store ``body`` for ``match_id``, stamped as ending now.

        ``audience`` is who ``body`` was built for. Replaces an earlier record
        for the same id. Raises :class:`TranscriptRejected` for an audience
        other than the public, an invalid id, or a body larger than
        ``policy.max_bytes``.
        """

    def get(self, match_id: str) -> StoredTranscript | None:
        """The record, or ``None`` if absent, expired, or the id is invalid."""

    def sweep(self) -> int:
        """Delete expired records. Returns how many were deleted."""

    def close(self) -> None:
        """Release files or connections. The store is unusable afterwards."""


def _check_put(policy: RetentionPolicy, match_id: str, body: bytes, audience: str) -> None:
    if audience != PUBLIC_AUDIENCE:
        raise TranscriptRejected(f"Only public transcripts are stored, not {audience!r}.")
    if not is_valid_match_id(match_id):
        raise TranscriptRejected("Not a valid match id.")
    if not isinstance(body, bytes):
        raise TranscriptRejected("A transcript body must be bytes.")
    if len(body) > policy.max_bytes:
        raise TranscriptRejected(
            f"The transcript is {len(body)} bytes; the store keeps at most "
            f"{policy.max_bytes}."
        )


class _Index:
    """Which records exist, when they ended, and how big they are.

    Shared by the memory and file backends. Records are kept in the order they
    ended (a put always ends now, and the clock only moves forward in practice;
    ``over_caps`` sorts anyway so a clock step backwards cannot pin a record).
    """

    def __init__(self) -> None:
        self.entries: OrderedDict[str, tuple[float, int]] = OrderedDict()
        self.total_bytes = 0

    def add(self, match_id: str, ended_at: float, size: int) -> None:
        self.discard(match_id)
        self.entries[match_id] = (ended_at, size)
        self.total_bytes += size

    def discard(self, match_id: str) -> None:
        old = self.entries.pop(match_id, None)
        if old is not None:
            self.total_bytes -= old[1]

    def expired(self, now: float, ttl_s: float) -> list[str]:
        return [mid for mid, (ended, _) in self.entries.items() if now - ended >= ttl_s]

    def over_caps(self, policy: RetentionPolicy) -> list[str]:
        """The oldest ids to drop so the rest fit the caps."""

        count, size = len(self.entries), self.total_bytes
        if count <= policy.max_entries and size <= policy.max_bytes:
            return []
        doomed: list[str] = []
        for mid, (_, entry_size) in sorted(self.entries.items(), key=lambda kv: kv[1][0]):
            if count <= policy.max_entries and size <= policy.max_bytes:
                break
            doomed.append(mid)
            count -= 1
            size -= entry_size
        return doomed


class MemoryTranscriptStore:
    """Public transcripts in process memory: survive eviction, not restarts."""

    def __init__(
        self,
        policy: RetentionPolicy | None = None,
        *,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self.policy = policy or RetentionPolicy(max_bytes=DEFAULT_MEMORY_MAX_BYTES)
        self._now = time_fn
        self._lock = threading.Lock()
        self._index = _Index()
        self._bodies: dict[str, bytes] = {}

    def put(self, match_id: str, body: bytes, *, audience: str) -> StoredTranscript:
        _check_put(self.policy, match_id, body, audience)
        with self._lock:
            now = self._now()
            self._index.add(match_id, now, len(body))
            self._bodies[match_id] = body
            self._drop(self._index.expired(now, self.policy.ttl_s))
            self._drop(self._index.over_caps(self.policy))
            return StoredTranscript(match_id, now, body)

    def get(self, match_id: str) -> StoredTranscript | None:
        if not is_valid_match_id(match_id):
            return None
        with self._lock:
            entry = self._index.entries.get(match_id)
            if entry is None:
                return None
            if self._now() - entry[0] >= self.policy.ttl_s:
                self._drop([match_id])
                return None
            return StoredTranscript(match_id, entry[0], self._bodies[match_id])

    def sweep(self) -> int:
        with self._lock:
            doomed = self._index.expired(self._now(), self.policy.ttl_s)
            self._drop(doomed)
            return len(doomed)

    def close(self) -> None:
        with self._lock:
            self._index = _Index()
            self._bodies.clear()

    def _drop(self, match_ids: list[str]) -> None:
        for mid in match_ids:
            self._index.discard(mid)
            self._bodies.pop(mid, None)


def _file_key(match_id: str) -> str:
    """A match id as a file name: lowercase hex of its bytes.

    Match ids are case-sensitive and Windows and macOS file names are not:
    ``Abc...`` and ``abc...`` are two matches but one file. Hex is also free of
    reserved device names (``CON``, ``NUL``, ...), dots, and separators.
    """

    return match_id.encode("ascii").hex()


class FileTranscriptStore:
    """One file per match: ``<hex(match_id)>.<ended_at_ms>.json``.

    The end time lives in the file name, not in the modification time, so
    copying or restoring the directory does not reset retention. Writes go to a
    temporary file first and are renamed into place, so a crash leaves either
    the old record or the new one, never half a file. The index of what exists
    is rebuilt from the directory on open.
    """

    _NAME = re.compile(r"(?P<key>(?:[0-9a-f]{2}){1,64})\.(?P<ms>[0-9]{1,17})\.json")
    _TMP_NAME = re.compile(r"\.(?:[0-9a-f]{2}){1,64}\.tmp")

    def __init__(
        self,
        directory: str | os.PathLike[str],
        policy: RetentionPolicy | None = None,
        *,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self.policy = policy or RetentionPolicy()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._now = time_fn
        self._lock = threading.Lock()
        self._index = _Index()
        self._files: dict[str, Path] = {}
        self._load()

    def _load(self) -> None:
        found: list[tuple[float, str, Path, int]] = []
        for entry in os.scandir(self.directory):
            if not entry.is_file(follow_symlinks=False):
                continue
            path = Path(entry.path)
            if self._TMP_NAME.fullmatch(entry.name):
                path.unlink(missing_ok=True)  # our interrupted write
                continue
            parsed = self._NAME.fullmatch(entry.name)
            if parsed is None:
                continue  # not ours: leave it alone
            try:
                mid = bytes.fromhex(parsed["key"]).decode("ascii")
            except (ValueError, UnicodeDecodeError):
                continue
            if not is_valid_match_id(mid):
                continue
            found.append((int(parsed["ms"]) / 1000, mid, path, entry.stat().st_size))
        with self._lock:
            for ended_at, mid, path, size in sorted(found):
                previous = self._files.get(mid)
                if previous is not None:
                    previous.unlink(missing_ok=True)  # a replaced record left behind
                self._index.add(mid, ended_at, size)
                self._files[mid] = path
            self._drop(self._index.expired(self._now(), self.policy.ttl_s))
            self._drop(self._index.over_caps(self.policy))

    def put(self, match_id: str, body: bytes, *, audience: str) -> StoredTranscript:
        _check_put(self.policy, match_id, body, audience)
        with self._lock:
            now = self._now()
            key = _file_key(match_id)
            path = self.directory / f"{key}.{int(now * 1000)}.json"
            tmp = self.directory / f".{key}.tmp"
            with open(tmp, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
            previous = self._files.get(match_id)
            if previous is not None and previous != path:
                previous.unlink(missing_ok=True)
            self._index.add(match_id, now, len(body))
            self._files[match_id] = path
            self._drop(self._index.expired(now, self.policy.ttl_s))
            self._drop(self._index.over_caps(self.policy))
            return StoredTranscript(match_id, now, body)

    def get(self, match_id: str) -> StoredTranscript | None:
        if not is_valid_match_id(match_id):
            return None
        with self._lock:
            entry = self._index.entries.get(match_id)
            if entry is None:
                return None
            if self._now() - entry[0] >= self.policy.ttl_s:
                self._drop([match_id])
                return None
            try:
                body = self._files[match_id].read_bytes()
            except FileNotFoundError:
                self._index.discard(match_id)  # deleted behind our back
                self._files.pop(match_id, None)
                return None
            return StoredTranscript(match_id, entry[0], body)

    def sweep(self) -> int:
        with self._lock:
            doomed = self._index.expired(self._now(), self.policy.ttl_s)
            self._drop(doomed)
            return len(doomed)

    def close(self) -> None:
        with self._lock:
            self._index = _Index()
            self._files.clear()

    def _drop(self, match_ids: list[str]) -> None:
        for mid in match_ids:
            self._index.discard(mid)
            path = self._files.pop(mid, None)
            if path is not None:
                path.unlink(missing_ok=True)


class SqliteTranscriptStore:
    """One row per match in a SQLite database file."""

    def __init__(
        self,
        path: str | os.PathLike[str],
        policy: RetentionPolicy | None = None,
        *,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self.policy = policy or RetentionPolicy()
        self.path = Path(path)
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._now = time_fn
        self._lock = threading.Lock()
        # One connection, serialized by the lock; the server calls in from
        # worker threads, hence check_same_thread=False.
        self._db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS public_transcripts ("
            " match_id TEXT PRIMARY KEY,"
            " ended_at REAL NOT NULL,"
            " size INTEGER NOT NULL,"
            " body BLOB NOT NULL)"
        )
        self._db.execute(
            "CREATE INDEX IF NOT EXISTS public_transcripts_ended_at"
            " ON public_transcripts (ended_at)"
        )
        with self._lock:
            self._expire(self._now())
            self._enforce_caps()

    def put(self, match_id: str, body: bytes, *, audience: str) -> StoredTranscript:
        _check_put(self.policy, match_id, body, audience)
        with self._lock:
            now = self._now()
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._db.execute(
                    "INSERT OR REPLACE INTO public_transcripts (match_id, ended_at, size, body)"
                    " VALUES (?, ?, ?, ?)",
                    (match_id, now, len(body), body),
                )
                self._expire(now)
                self._enforce_caps()
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
            self._db.execute("COMMIT")
            return StoredTranscript(match_id, now, body)

    def get(self, match_id: str) -> StoredTranscript | None:
        if not is_valid_match_id(match_id):
            return None
        with self._lock:
            row = self._db.execute(
                "SELECT ended_at, body FROM public_transcripts WHERE match_id = ?",
                (match_id,),
            ).fetchone()
            if row is None:
                return None
            ended_at, body = row
            if self._now() - ended_at >= self.policy.ttl_s:
                self._db.execute(
                    "DELETE FROM public_transcripts WHERE match_id = ?", (match_id,)
                )
                return None
            return StoredTranscript(match_id, ended_at, bytes(body))

    def sweep(self) -> int:
        with self._lock:
            return self._expire(self._now())

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def _expire(self, now: float) -> int:
        cursor = self._db.execute(
            "DELETE FROM public_transcripts WHERE ended_at <= ?", (now - self.policy.ttl_s,)
        )
        return cursor.rowcount

    def _enforce_caps(self) -> None:
        count, size = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM public_transcripts"
        ).fetchone()
        if count <= self.policy.max_entries and size <= self.policy.max_bytes:
            return
        doomed: list[str] = []
        for mid, entry_size in self._db.execute(
            "SELECT match_id, size FROM public_transcripts ORDER BY ended_at, match_id"
        ):
            if count <= self.policy.max_entries and size <= self.policy.max_bytes:
                break
            doomed.append(mid)
            count -= 1
            size -= entry_size
        self._db.executemany(
            "DELETE FROM public_transcripts WHERE match_id = ?", [(mid,) for mid in doomed]
        )


def open_transcript_store(spec: str, policy: RetentionPolicy | None = None) -> TranscriptStore:
    """Build a store from a spec: ``memory``, ``file:DIR``, or ``sqlite:PATH``."""

    kind, _, target = spec.partition(":")
    if kind == "memory" and not target:
        return MemoryTranscriptStore(policy)
    if kind == "file" and target:
        return FileTranscriptStore(target, policy)
    if kind == "sqlite" and target:
        return SqliteTranscriptStore(target, policy)
    raise ValueError(
        f"Unknown transcript store {spec!r}: expected 'memory', 'file:DIR', or 'sqlite:PATH'."
    )


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MEMORY_MAX_BYTES",
    "DEFAULT_TTL_S",
    "FileTranscriptStore",
    "MemoryTranscriptStore",
    "PUBLIC_AUDIENCE",
    "RetentionPolicy",
    "SqliteTranscriptStore",
    "StoredTranscript",
    "TranscriptRejected",
    "TranscriptStore",
    "is_valid_match_id",
    "open_transcript_store",
]
