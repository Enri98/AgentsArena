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
plus caps on the number of records, their total size, and each record's size.
Room for a new record is made **before** it is written, oldest first, so a
store at its cap (or a disk that filled) recovers by evicting rather than
failing every write from then on. Expiry is checked on every read, so an
expired record is gone at once (``404``) whether or not a sweep has run yet.
Stores are thread-safe; the server calls them from worker threads so disk I/O
never blocks the event loop.

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
#: Durable backends. Well below the 1 GB volume the deployment guide suggests:
#: file-system overhead and SQLite's WAL need headroom, and a full disk is
#: worse than an evicted transcript.
DEFAULT_MAX_BYTES: int = 512 << 20
#: The in-memory default shares the process with everything else.
DEFAULT_MEMORY_MAX_BYTES: int = 64 << 20
#: Largest single transcript kept. Eviction is global and oldest-first, so one
#: record pushes out others; bounding each record bounds how much one match
#: can. A 5000-turn Pig match is about 2 MB.
DEFAULT_MAX_RECORD_BYTES: int = 8 << 20
DEFAULT_MEMORY_MAX_RECORD_BYTES: int = 4 << 20
#: A record dated more than this in the future is re-dated to now. The wall
#: clock can step forward and back (NTP, a restored VM). Deleting such records
#: would erase every transcript whenever the clock stepped back; keeping their
#: dates would let them outlive the TTL and always sort as newest.
FUTURE_SLACK_S: float = 300.0

#: Match ids are ``secrets.token_urlsafe(16)``. Anything else is refused before
#: it reaches a path or a query, so an id cannot traverse out of the directory.
_MATCH_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def is_valid_match_id(match_id: object) -> bool:
    return isinstance(match_id, str) and _MATCH_ID.fullmatch(match_id) is not None


class TranscriptRejected(ValueError):
    """A transcript the store will not keep (not public, too large, bad id)."""


class StoreClosed(RuntimeError):
    """The store was closed (the server is shutting down)."""


@dataclass(frozen=True)
class RetentionPolicy:
    """How long, and how many, public transcripts are kept.

    ``ttl_s`` counts from the moment the match ended. Before a record is
    written, the records that ended first are dropped until it fits under
    ``max_entries`` and ``max_bytes``. A transcript larger than
    ``record_limit`` (the smaller of ``max_record_bytes`` and ``max_bytes``) is
    not stored.
    """

    ttl_s: float = DEFAULT_TTL_S
    max_entries: int = DEFAULT_MAX_ENTRIES
    max_bytes: int = DEFAULT_MAX_BYTES
    max_record_bytes: int = DEFAULT_MAX_RECORD_BYTES

    def __post_init__(self) -> None:
        if not self.ttl_s > 0:
            raise ValueError(f"ttl_s must be positive, got {self.ttl_s!r}.")
        if self.max_entries < 1:
            raise ValueError(f"max_entries must be at least 1, got {self.max_entries!r}.")
        if self.max_bytes < 1:
            raise ValueError(f"max_bytes must be at least 1, got {self.max_bytes!r}.")
        if self.max_record_bytes < 1:
            raise ValueError(
                f"max_record_bytes must be at least 1, got {self.max_record_bytes!r}."
            )

    @property
    def record_limit(self) -> int:
        return min(self.max_record_bytes, self.max_bytes)

    def is_expired(self, ended_at: float, now: float) -> bool:
        return now - ended_at >= self.ttl_s


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
        other than the public, an invalid id, or a body over
        ``policy.record_limit``; :class:`StoreClosed` after ``close``.
        """

    def get(self, match_id: str) -> StoredTranscript | None:
        """The record, or ``None`` if absent, expired, or the id is invalid."""

    def sweep(self) -> int:
        """Delete expired records. Returns how many were deleted."""

    def close(self) -> None:
        """Release files or connections. Afterwards ``put`` raises ``StoreClosed``
        and ``get`` finds nothing."""


def _check_put(policy: RetentionPolicy, match_id: str, body: bytes, audience: str) -> None:
    if audience != PUBLIC_AUDIENCE:
        raise TranscriptRejected(f"Only public transcripts are stored, not {audience!r}.")
    if not is_valid_match_id(match_id):
        raise TranscriptRejected("Not a valid match id.")
    if not isinstance(body, bytes):
        raise TranscriptRejected("A transcript body must be bytes.")
    if len(body) > policy.record_limit:
        raise TranscriptRejected(
            f"The transcript is {len(body)} bytes; the store keeps transcripts of at "
            f"most {policy.record_limit}."
        )


class _Index:
    """Which records exist, when they ended, and how big they are.

    Shared by the memory and file backends.
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

    def clamp_future(self, now: float) -> None:
        for mid, (ended, size) in list(self.entries.items()):
            if ended - now > FUTURE_SLACK_S:
                self.entries[mid] = (now, size)

    def expired(self, now: float, policy: RetentionPolicy) -> list[str]:
        return [
            mid for mid, (ended, _) in self.entries.items() if policy.is_expired(ended, now)
        ]

    def room_for(self, policy: RetentionPolicy, match_id: str, size: int) -> list[str]:
        """The oldest ids to drop so a ``size``-byte record for ``match_id`` fits.

        ``match_id``'s own earlier record, which the new one replaces, is not
        counted and not dropped here.
        """

        old = self.entries.get(match_id)
        count = len(self.entries) + (0 if old is not None else 1)
        total = self.total_bytes - (old[1] if old is not None else 0) + size
        doomed: list[str] = []
        for mid, (_, entry_size) in sorted(self.entries.items(), key=lambda kv: kv[1][0]):
            if count <= policy.max_entries and total <= policy.max_bytes:
                break
            if mid == match_id:
                continue
            doomed.append(mid)
            count -= 1
            total -= entry_size
        return doomed

    def over_caps(self, policy: RetentionPolicy) -> list[str]:
        """The oldest ids to drop so the rest fit the caps (tightened on reopen)."""

        count, total = len(self.entries), self.total_bytes
        doomed: list[str] = []
        for mid, (_, entry_size) in sorted(self.entries.items(), key=lambda kv: kv[1][0]):
            if count <= policy.max_entries and total <= policy.max_bytes:
                break
            doomed.append(mid)
            count -= 1
            total -= entry_size
        return doomed


class MemoryTranscriptStore:
    """Public transcripts in process memory: survive eviction, not restarts."""

    def __init__(
        self,
        policy: RetentionPolicy | None = None,
        *,
        time_fn: Callable[[], float] = time.time,
    ) -> None:
        self.policy = policy or RetentionPolicy(
            max_bytes=DEFAULT_MEMORY_MAX_BYTES,
            max_record_bytes=DEFAULT_MEMORY_MAX_RECORD_BYTES,
        )
        self._now = time_fn
        self._lock = threading.Lock()
        self._index = _Index()
        self._bodies: dict[str, bytes] = {}
        self._closed = False

    def put(self, match_id: str, body: bytes, *, audience: str) -> StoredTranscript:
        _check_put(self.policy, match_id, body, audience)
        with self._lock:
            if self._closed:
                raise StoreClosed("The transcript store is closed.")
            now = self._now()
            self._index.clamp_future(now)
            self._drop(self._index.expired(now, self.policy))
            self._drop(self._index.room_for(self.policy, match_id, len(body)))
            self._index.add(match_id, now, len(body))
            self._bodies[match_id] = body
            return StoredTranscript(match_id, now, body)

    def get(self, match_id: str) -> StoredTranscript | None:
        if not is_valid_match_id(match_id):
            return None
        with self._lock:
            now = self._now()
            self._index.clamp_future(now)
            entry = self._index.entries.get(match_id)
            if entry is None:
                return None
            if self.policy.is_expired(entry[0], now):
                self._drop([match_id])
                return None
            return StoredTranscript(match_id, entry[0], self._bodies[match_id])

    def sweep(self) -> int:
        with self._lock:
            now = self._now()
            self._index.clamp_future(now)
            doomed = self._index.expired(now, self.policy)
            self._drop(doomed)
            return len(doomed)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._index = _Index()
            self._bodies.clear()

    def _drop(self, match_ids: list[str]) -> None:
        for mid in match_ids:
            self._index.discard(mid)
            self._bodies.pop(mid, None)


def _fsync_directory(directory: Path) -> None:
    """Make a rename or unlink in ``directory`` durable (POSIX only).

    Windows has no directory handle to fsync; NTFS journals the rename.
    """

    if os.name == "nt":
        return
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


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
    is rebuilt from the directory on open. Reads happen outside the store's
    lock, so a large read does not hold up other matches' writes.
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
        # Files that could not be deleted yet (Windows refuses to delete a file
        # another process holds open: an indexer, a backup, a virus scanner).
        # Out of the index already; retried on every put and sweep.
        self._orphans: set[Path] = set()
        self._closed = False
        self._load()

    def _load(self) -> None:
        found: list[tuple[float, str, Path, int]] = []
        for entry in os.scandir(self.directory):
            if not entry.is_file(follow_symlinks=False):
                continue
            path = Path(entry.path)
            if self._TMP_NAME.fullmatch(entry.name):
                self._unlink(path)  # our interrupted write
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
                    self._unlink(previous)  # a replaced record left behind
                self._index.add(mid, ended_at, size)
                self._files[mid] = path
            now = self._now()
            self._index.clamp_future(now)
            self._drop(self._index.expired(now, self.policy))
            self._drop(self._index.over_caps(self.policy))

    def put(self, match_id: str, body: bytes, *, audience: str) -> StoredTranscript:
        _check_put(self.policy, match_id, body, audience)
        with self._lock:
            if self._closed:
                raise StoreClosed("The transcript store is closed.")
            self._retry_orphans()
            now = self._now()
            self._index.clamp_future(now)
            self._drop(self._index.expired(now, self.policy))
            # Room first: evicting only after a successful write meant a full
            # disk refused every write from then on.
            self._drop(self._index.room_for(self.policy, match_id, len(body)))
            key = _file_key(match_id)
            path = self.directory / f"{key}.{int(now * 1000)}.json"
            tmp = self.directory / f".{key}.tmp"
            try:
                with open(tmp, "wb") as handle:
                    handle.write(body)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp, path)
            except BaseException:
                self._unlink(tmp)  # a partial file must not pile up uncounted
                raise
            _fsync_directory(self.directory)
            # The new file is in place: the index follows it before anything
            # else can fail, so a get never serves the replaced body.
            previous = self._files.get(match_id)
            self._index.add(match_id, now, len(body))
            self._files[match_id] = path
            if previous is not None and previous != path:
                self._unlink(previous)
            return StoredTranscript(match_id, now, body)

    def get(self, match_id: str) -> StoredTranscript | None:
        if not is_valid_match_id(match_id):
            return None
        with self._lock:
            now = self._now()
            self._index.clamp_future(now)
            entry = self._index.entries.get(match_id)
            if entry is None:
                return None
            if self.policy.is_expired(entry[0], now):
                self._drop([match_id])
                return None
            path = self._files[match_id]
        try:
            body = path.read_bytes()
        except FileNotFoundError:
            # Replaced or evicted since the lookup, or deleted behind our back.
            with self._lock:
                if self._files.get(match_id) == path:
                    self._index.discard(match_id)
                    self._files.pop(match_id, None)
            return None
        return StoredTranscript(match_id, entry[0], body)

    def sweep(self) -> int:
        with self._lock:
            self._retry_orphans()
            now = self._now()
            self._index.clamp_future(now)
            doomed = self._index.expired(now, self.policy)
            self._drop(doomed)
            return len(doomed)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._index = _Index()
            self._files.clear()

    def _drop(self, match_ids: list[str]) -> None:
        for mid in match_ids:
            self._index.discard(mid)
            path = self._files.pop(mid, None)
            if path is not None:
                self._unlink(path)

    def _unlink(self, path: Path) -> None:
        """Delete ``path`` if possible; remember it for a retry if not."""

        try:
            path.unlink(missing_ok=True)
        except OSError:
            self._orphans.add(path)
        else:
            self._orphans.discard(path)

    def _retry_orphans(self) -> None:
        for path in list(self._orphans):
            self._unlink(path)


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
        self._closed = False
        with self._lock:
            now = self._now()
            self._clamp_future(now)
            self._expire(now)
            self._make_room(None, 0)

    def put(self, match_id: str, body: bytes, *, audience: str) -> StoredTranscript:
        _check_put(self.policy, match_id, body, audience)
        with self._lock:
            if self._closed:
                raise StoreClosed("The transcript store is closed.")
            now = self._now()
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._clamp_future(now)
                self._expire(now)
                # Room first: a full disk then frees space in the same
                # transaction instead of refusing every write from then on.
                self._make_room(match_id, len(body))
                self._db.execute(
                    "INSERT OR REPLACE INTO public_transcripts (match_id, ended_at, size, body)"
                    " VALUES (?, ?, ?, ?)",
                    (match_id, now, len(body), body),
                )
                self._db.execute("COMMIT")
            except BaseException:
                # SQLite may have rolled back itself (SQLITE_FULL does); a second
                # ROLLBACK would raise and hide the real error.
                if self._db.in_transaction:
                    self._db.execute("ROLLBACK")
                raise
            return StoredTranscript(match_id, now, body)

    def get(self, match_id: str) -> StoredTranscript | None:
        if not is_valid_match_id(match_id):
            return None
        with self._lock:
            if self._closed:
                return None
            now = self._now()
            self._clamp_future(now)
            row = self._db.execute(
                "SELECT ended_at, body FROM public_transcripts WHERE match_id = ?",
                (match_id,),
            ).fetchone()
            if row is None:
                return None
            ended_at, body = row
            if self.policy.is_expired(ended_at, now):
                self._db.execute(
                    "DELETE FROM public_transcripts WHERE match_id = ?", (match_id,)
                )
                return None
            return StoredTranscript(match_id, ended_at, bytes(body))

    def sweep(self) -> int:
        with self._lock:
            if self._closed:
                return 0
            now = self._now()
            self._clamp_future(now)
            return self._expire(now)

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._db.close()

    def _clamp_future(self, now: float) -> None:
        self._db.execute(
            "UPDATE public_transcripts SET ended_at = ? WHERE ended_at > ?",
            (now, now + FUTURE_SLACK_S),
        )

    def _expire(self, now: float) -> int:
        cursor = self._db.execute(
            "DELETE FROM public_transcripts WHERE ended_at <= ?", (now - self.policy.ttl_s,)
        )
        return cursor.rowcount

    def _make_room(self, match_id: str | None, size: int) -> None:
        """Drop the oldest rows until ``size`` more bytes for ``match_id`` fit."""

        count, total = self._db.execute(
            "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM public_transcripts"
        ).fetchone()
        if match_id is not None:
            old = self._db.execute(
                "SELECT size FROM public_transcripts WHERE match_id = ?", (match_id,)
            ).fetchone()
            count += 0 if old is not None else 1
            total += size - (old[0] if old is not None else 0)
        if count <= self.policy.max_entries and total <= self.policy.max_bytes:
            return
        doomed: list[str] = []
        for mid, entry_size in self._db.execute(
            "SELECT match_id, size FROM public_transcripts ORDER BY ended_at, match_id"
        ):
            if count <= self.policy.max_entries and total <= self.policy.max_bytes:
                break
            if mid == match_id:
                continue
            doomed.append(mid)
            count -= 1
            total -= entry_size
        self._db.executemany(
            "DELETE FROM public_transcripts WHERE match_id = ?", [(mid,) for mid in doomed]
        )


def open_transcript_store(spec: str, policy: RetentionPolicy | None = None) -> TranscriptStore:
    """Build a store from a spec: ``memory``, ``file:DIR``, or ``sqlite:PATH``.

    Raises ``ValueError`` for a malformed spec, and ``OSError`` /
    ``sqlite3.Error`` when the location cannot be opened.
    """

    kind, sep, target = spec.partition(":")
    target = target.strip()
    if spec == "memory":
        return MemoryTranscriptStore(policy)
    if kind == "file" and target:
        return FileTranscriptStore(target, policy)
    if kind == "sqlite" and target and target != ":memory:" and not target.startswith("file:"):
        return SqliteTranscriptStore(target, policy)
    raise ValueError(
        f"Unknown transcript store {spec!r}: expected 'memory', 'file:DIR', or "
        "'sqlite:PATH' (a real file path)."
    )


__all__ = [
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_ENTRIES",
    "DEFAULT_MAX_RECORD_BYTES",
    "DEFAULT_MEMORY_MAX_BYTES",
    "DEFAULT_MEMORY_MAX_RECORD_BYTES",
    "DEFAULT_TTL_S",
    "FUTURE_SLACK_S",
    "FileTranscriptStore",
    "MemoryTranscriptStore",
    "PUBLIC_AUDIENCE",
    "RetentionPolicy",
    "SqliteTranscriptStore",
    "StoreClosed",
    "StoredTranscript",
    "TranscriptRejected",
    "TranscriptStore",
    "is_valid_match_id",
    "open_transcript_store",
]
