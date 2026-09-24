"""The transcript store contract, run against every backend (Phase 40 Slice 1)."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from arena.server.transcript_store import (
    FileTranscriptStore,
    MemoryTranscriptStore,
    RetentionPolicy,
    SqliteTranscriptStore,
    TranscriptRejected,
    TranscriptStore,
    is_valid_match_id,
    open_transcript_store,
)

MID = "Abc_def-0123456789xyzQ"  # the shape of secrets.token_urlsafe(16)


class Clock:
    def __init__(self, now: float = 1_700_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


Factory = Callable[[RetentionPolicy, Clock], TranscriptStore]


@pytest.fixture(params=["memory", "file", "sqlite"])
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> str:
    return request.param


def _factory(backend: str, tmp_path: Path) -> Factory:
    def make(policy: RetentionPolicy, clock: Clock) -> TranscriptStore:
        if backend == "memory":
            return MemoryTranscriptStore(policy, time_fn=clock)
        if backend == "file":
            return FileTranscriptStore(tmp_path / "transcripts", policy, time_fn=clock)
        return SqliteTranscriptStore(tmp_path / "db" / "transcripts.sqlite3", policy, time_fn=clock)

    return make


@pytest.fixture
def make(backend: str, tmp_path: Path) -> Factory:
    stores: list[TranscriptStore] = []
    factory = _factory(backend, tmp_path)

    def tracked(policy: RetentionPolicy | None = None, clock: Clock | None = None):
        store = factory(policy or RetentionPolicy(), clock or Clock())
        stores.append(store)
        return store

    yield tracked
    for store in stores:
        store.close()


def _mid(i: int) -> str:
    return f"match{i:04d}"


# ── Basic contract ─────────────────────────────────────────────────────────


def test_a_stored_transcript_comes_back_byte_for_byte(make) -> None:
    clock = Clock()
    store = make(clock=clock)
    body = '{"view": "public", "note": "é"}'.encode()
    record = store.put(MID, body, audience="public")
    assert record.ended_at == clock.now
    got = store.get(MID)
    assert got is not None
    assert (got.match_id, got.body, got.ended_at) == (MID, body, clock.now)


def test_an_unknown_match_is_absent(make) -> None:
    assert make().get(MID) is None


@pytest.mark.parametrize("audience", ["full", "seat", "", "PUBLIC", "0"])
def test_only_public_transcripts_are_stored(make, audience: str) -> None:
    store = make()
    with pytest.raises(TranscriptRejected):
        store.put(MID, b"{}", audience=audience)
    assert store.get(MID) is None


@pytest.mark.parametrize(
    "bad_id",
    ["", "../etc", "a/b", "a\\b", "a.b", "..", "x" * 65, "café", "a b", "a\x00b"],
)
def test_an_invalid_match_id_is_refused_and_never_found(make, bad_id: str) -> None:
    store = make()
    with pytest.raises(TranscriptRejected):
        store.put(bad_id, b"{}", audience="public")
    assert store.get(bad_id) is None


def test_a_non_string_id_is_never_found(make) -> None:
    assert make().get(None) is None  # type: ignore[arg-type]
    assert not is_valid_match_id(123)


def test_a_non_bytes_body_is_refused(make) -> None:
    with pytest.raises(TranscriptRejected):
        make().put(MID, "{}", audience="public")  # type: ignore[arg-type]


def test_a_transcript_larger_than_the_byte_cap_is_refused(make) -> None:
    store = make(RetentionPolicy(max_bytes=10))
    with pytest.raises(TranscriptRejected):
        store.put(MID, b"x" * 11, audience="public")
    assert store.get(MID) is None
    store.put(MID, b"x" * 10, audience="public")
    assert store.get(MID) is not None


def test_a_second_put_replaces_the_first(make) -> None:
    clock = Clock()
    store = make(clock=clock)
    store.put(MID, b"one", audience="public")
    clock.now += 5
    store.put(MID, b"two", audience="public")
    got = store.get(MID)
    assert got is not None and got.body == b"two" and got.ended_at == clock.now


# ── Retention ──────────────────────────────────────────────────────────────


def test_a_transcript_expires_exactly_at_its_ttl(make) -> None:
    clock = Clock()
    store = make(RetentionPolicy(ttl_s=100), clock)
    store.put(MID, b"{}", audience="public")
    clock.now += 99.9
    assert store.get(MID) is not None
    clock.now += 0.1
    assert store.get(MID) is None
    clock.now -= 50  # a clock stepping back does not resurrect it
    assert store.get(MID) is None


def test_sweep_deletes_only_expired_transcripts(make) -> None:
    clock = Clock()
    store = make(RetentionPolicy(ttl_s=100), clock)
    store.put(_mid(1), b"{}", audience="public")
    clock.now += 60
    store.put(_mid(2), b"{}", audience="public")
    clock.now += 50
    assert store.sweep() == 1
    assert store.get(_mid(1)) is None
    assert store.get(_mid(2)) is not None
    assert store.sweep() == 0


def test_a_put_sweeps_expired_transcripts(make) -> None:
    clock = Clock()
    store = make(RetentionPolicy(ttl_s=100), clock)
    store.put(_mid(1), b"{}", audience="public")
    clock.now += 100
    store.put(_mid(2), b"{}", audience="public")
    assert store.sweep() == 0  # the put already removed match 1


def test_the_entry_cap_drops_the_oldest(make) -> None:
    clock = Clock()
    store = make(RetentionPolicy(max_entries=3), clock)
    for i in range(5):
        store.put(_mid(i), b"{}", audience="public")
        clock.now += 1
    assert [store.get(_mid(i)) is not None for i in range(5)] == [False, False, True, True, True]


def test_the_byte_cap_drops_the_oldest(make) -> None:
    clock = Clock()
    store = make(RetentionPolicy(max_bytes=25), clock)
    for i in range(4):
        store.put(_mid(i), b"x" * 10, audience="public")
        clock.now += 1
    # 40 bytes stored; the two oldest go to get under 25.
    assert [store.get(_mid(i)) is not None for i in range(4)] == [False, False, True, True]


def test_replacing_a_transcript_counts_its_bytes_once(make) -> None:
    store = make(RetentionPolicy(max_bytes=25))
    store.put(_mid(1), b"x" * 10, audience="public")
    for _ in range(5):
        store.put(_mid(2), b"x" * 10, audience="public")
    assert store.get(_mid(1)) is not None


@pytest.mark.parametrize(
    "kwargs",
    [{"ttl_s": 0}, {"ttl_s": -1}, {"max_entries": 0}, {"max_bytes": 0}],
)
def test_a_retention_policy_must_be_positive(kwargs: dict) -> None:
    with pytest.raises(ValueError):
        RetentionPolicy(**kwargs)


def test_concurrent_puts_and_gets_are_safe(make) -> None:
    store = make(RetentionPolicy(max_entries=50))
    errors: list[BaseException] = []

    def work(worker: int) -> None:
        try:
            for i in range(40):
                mid = f"w{worker}m{i}"
                store.put(mid, mid.encode(), audience="public")
                got = store.get(mid)
                assert got is None or got.body == mid.encode()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(w,)) for w in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


# ── Durable backends ───────────────────────────────────────────────────────


@pytest.mark.parametrize("durable", ["file", "sqlite"])
def test_a_durable_store_survives_reopening(durable: str, tmp_path: Path) -> None:
    factory = _factory(durable, tmp_path)
    clock = Clock()
    first = factory(RetentionPolicy(ttl_s=100), clock)
    first.put(_mid(1), b"one", audience="public")
    clock.now += 60
    first.put(_mid(2), b"two", audience="public")
    first.close()

    second = factory(RetentionPolicy(ttl_s=100), clock)
    try:
        assert second.get(_mid(1)).body == b"one"  # type: ignore[union-attr]
        assert second.get(_mid(2)).ended_at == clock.now  # type: ignore[union-attr]
        clock.now += 40  # retention counts from the original end, not the reopen
        assert second.get(_mid(1)) is None
        assert second.get(_mid(2)) is not None
    finally:
        second.close()


@pytest.mark.parametrize("durable", ["file", "sqlite"])
def test_reopening_with_tighter_caps_applies_them(durable: str, tmp_path: Path) -> None:
    factory = _factory(durable, tmp_path)
    clock = Clock()
    first = factory(RetentionPolicy(), clock)
    for i in range(4):
        first.put(_mid(i), b"{}", audience="public")
        clock.now += 1
    first.close()
    second = factory(RetentionPolicy(max_entries=2), clock)
    try:
        assert [second.get(_mid(i)) is not None for i in range(4)] == [False, False, True, True]
    finally:
        second.close()


HEX = MID.encode().hex()


def test_the_file_store_names_files_by_end_time(tmp_path: Path) -> None:
    clock = Clock(1_700_000_000.25)
    store = FileTranscriptStore(tmp_path, time_fn=clock)
    store.put(MID, b"{}", audience="public")
    assert sorted(os.listdir(tmp_path)) == [f"{HEX}.1700000000250.json"]
    clock.now += 1
    store.put(MID, b"{}", audience="public")
    assert sorted(os.listdir(tmp_path)) == [f"{HEX}.1700000001250.json"]


def test_ids_differing_only_in_case_are_different_files(tmp_path: Path) -> None:
    # Windows and macOS file names are case-insensitive; match ids are not.
    store = FileTranscriptStore(tmp_path, time_fn=Clock())
    store.put("AbcDef", b"upper", audience="public")
    store.put("abcdef", b"lower", audience="public")
    assert store.get("AbcDef").body == b"upper"  # type: ignore[union-attr]
    assert store.get("abcdef").body == b"lower"  # type: ignore[union-attr]
    reopened = FileTranscriptStore(tmp_path, time_fn=Clock())
    assert reopened.get("AbcDef").body == b"upper"  # type: ignore[union-attr]


def test_the_file_store_ignores_foreign_files_and_clears_its_own_leftovers(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.txt").write_text("keep me")
    (tmp_path / "notes.tmp").write_text("keep me too")
    (tmp_path / f".{HEX}.tmp").write_bytes(b"half a transcript")
    (tmp_path / "subdir.1.json").mkdir()
    store = FileTranscriptStore(tmp_path, time_fn=Clock())
    assert sorted(os.listdir(tmp_path)) == ["README.txt", "notes.tmp", "subdir.1.json"]
    assert store.get(MID) is None


def test_the_file_store_keeps_the_newest_of_duplicate_records(tmp_path: Path) -> None:
    clock = Clock(2_000.0)
    (tmp_path / f"{HEX}.1000000.json").write_bytes(b"old")
    (tmp_path / f"{HEX}.1500000.json").write_bytes(b"new")
    store = FileTranscriptStore(tmp_path, time_fn=clock)
    got = store.get(MID)
    assert got is not None and got.body == b"new" and got.ended_at == 1500.0
    assert os.listdir(tmp_path) == [f"{HEX}.1500000.json"]


def test_the_file_store_forgets_a_file_deleted_behind_its_back(tmp_path: Path) -> None:
    store = FileTranscriptStore(tmp_path, time_fn=Clock())
    store.put(MID, b"{}", audience="public")
    for name in os.listdir(tmp_path):
        os.remove(tmp_path / name)
    assert store.get(MID) is None


def test_expired_files_are_deleted_from_disk(tmp_path: Path) -> None:
    clock = Clock()
    store = FileTranscriptStore(tmp_path, RetentionPolicy(ttl_s=10), time_fn=clock)
    store.put(MID, b"{}", audience="public")
    clock.now += 10
    assert store.sweep() == 1
    assert os.listdir(tmp_path) == []


# ── Specs ──────────────────────────────────────────────────────────────────


def test_open_transcript_store_parses_specs(tmp_path: Path) -> None:
    memory = open_transcript_store("memory")
    assert isinstance(memory, MemoryTranscriptStore)
    files = open_transcript_store(f"file:{tmp_path / 'files'}")
    assert isinstance(files, FileTranscriptStore)
    db = open_transcript_store(f"sqlite:{tmp_path / 'arena.sqlite3'}")
    assert isinstance(db, SqliteTranscriptStore)
    for store in (memory, files, db):
        store.close()


@pytest.mark.parametrize(
    "spec",
    ["", "memory:x", "memory:", "file", "file:", "file:  ", "sqlite", "sqlite::memory:",
     "sqlite:file:x?mode=memory", "postgres:x"],
)
def test_open_transcript_store_refuses_unknown_specs(spec: str) -> None:
    with pytest.raises(ValueError):
        open_transcript_store(spec)


def test_the_memory_default_is_bounded_below_the_durable_default() -> None:
    assert MemoryTranscriptStore().policy.max_bytes < RetentionPolicy().max_bytes


# ── Review of Slice 1 ──────────────────────────────────────────────────────


def test_a_record_from_the_future_is_redated_and_then_expires(make) -> None:
    from arena.server.transcript_store import FUTURE_SLACK_S

    clock = Clock()
    store = make(RetentionPolicy(ttl_s=100), clock)
    clock.now += FUTURE_SLACK_S + 3600  # the wall clock jumps forward...
    store.put(_mid(1), b"{}", audience="public")
    clock.now -= FUTURE_SLACK_S + 3600  # ...and is corrected
    got = store.get(_mid(1))
    assert got is not None and got.ended_at == clock.now  # re-dated to now
    clock.now += 100
    assert store.get(_mid(1)) is None  # and it expires on the normal TTL


def test_a_clock_stepping_back_deletes_nothing(make) -> None:
    from arena.server.transcript_store import FUTURE_SLACK_S

    clock = Clock()
    store = make(RetentionPolicy(ttl_s=10_000), clock)
    for i in range(5):
        store.put(_mid(i), b"{}", audience="public")
    clock.now -= FUTURE_SLACK_S + 600  # every record now looks future-dated
    store.put(_mid(9), b"{}", audience="public")
    store.sweep()
    assert all(store.get(_mid(i)) is not None for i in (0, 1, 2, 3, 4, 9))


def test_room_is_made_before_the_write(make) -> None:
    clock = Clock()
    store = make(RetentionPolicy(max_bytes=30), clock)
    store.put(_mid(1), b"x" * 15, audience="public")
    clock.now += 1
    store.put(_mid(2), b"x" * 15, audience="public")
    clock.now += 1
    # 30 bytes held; a 20-byte record needs both older ones gone first.
    store.put(_mid(3), b"x" * 20, audience="public")
    assert [store.get(_mid(i)) is not None for i in (1, 2, 3)] == [False, False, True]


def test_a_put_after_the_clock_stepped_back_is_kept(make) -> None:
    clock = Clock()
    store = make(RetentionPolicy(max_entries=2), clock)
    store.put(_mid(1), b"{}", audience="public")
    store.put(_mid(2), b"{}", audience="public")
    clock.now -= 60
    store.put(_mid(3), b"{}", audience="public")
    assert store.get(_mid(3)) is not None


def test_a_record_over_the_per_record_cap_is_refused(make) -> None:
    store = make(RetentionPolicy(max_bytes=1000, max_record_bytes=100))
    with pytest.raises(TranscriptRejected):
        store.put(MID, b"x" * 101, audience="public")
    store.put(MID, b"x" * 100, audience="public")


def test_a_closed_store_refuses_puts_and_finds_nothing(make) -> None:
    from arena.server.transcript_store import StoreClosed

    store = make()
    store.put(MID, b"{}", audience="public")
    store.close()
    with pytest.raises(StoreClosed):
        store.put(MID, b"{}", audience="public")
    assert store.get(MID) is None
    assert store.sweep() == 0
    store.close()  # idempotent


def test_a_locked_file_does_not_break_the_file_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Windows refuses to delete a file another process holds open.
    clock = Clock()
    store = FileTranscriptStore(tmp_path, RetentionPolicy(ttl_s=100), time_fn=clock)
    store.put(MID, b"old", audience="public")
    real_unlink = Path.unlink
    locked = True

    def unlink(self: Path, missing_ok: bool = False) -> None:
        if locked:
            raise PermissionError(32, "in use")
        real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", unlink)
    clock.now += 1
    store.put(MID, b"new", audience="public")  # the old file cannot go yet
    assert store.get(MID).body == b"new"  # type: ignore[union-attr]
    clock.now += 200
    assert store.sweep() == 1  # does not raise either
    locked = False
    store.sweep()  # the retry deletes both leftovers
    assert os.listdir(tmp_path) == []


def test_a_failed_file_write_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import builtins

    store = FileTranscriptStore(tmp_path, time_fn=Clock())
    real_open = builtins.open

    class Full:
        def __init__(self, handle):  # type: ignore[no-untyped-def]
            self.handle = handle

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *exc):  # type: ignore[no-untyped-def]
            self.handle.close()

        def write(self, data: bytes) -> int:
            raise OSError(28, "No space left on device")

    def full_open(path, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        handle = real_open(path, mode, *args, **kwargs)
        return Full(handle) if "w" in mode and str(path).endswith(".tmp") else handle

    monkeypatch.setattr(builtins, "open", full_open)
    with pytest.raises(OSError):
        store.put(MID, b"{}", audience="public")
    monkeypatch.setattr(builtins, "open", real_open)
    assert os.listdir(tmp_path) == []
    store.put(MID, b"{}", audience="public")  # and the store still works
    assert store.get(MID) is not None


def test_a_sqlite_store_keeps_writing_when_the_disk_fills(tmp_path: Path) -> None:
    clock = Clock()
    # Generous caps: the disk (max_page_count stands in for it) fills first.
    policy = RetentionPolicy(ttl_s=10**6)
    store = SqliteTranscriptStore(tmp_path / "t.sqlite3", policy, time_fn=clock)
    try:
        store._db.execute("PRAGMA max_page_count = 40")
        big = b"x" * 60_000
        for i in range(30):
            clock.now += 1
            store.put(_mid(i), big, audience="public")  # evicts the oldest, retries
        assert store.get(_mid(29)) is not None
        assert store.get(_mid(0)) is None
    finally:
        store.close()


def test_a_file_store_keeps_writing_when_the_disk_fills(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    clock = Clock()
    store = FileTranscriptStore(tmp_path, RetentionPolicy(ttl_s=10**6), time_fn=clock)
    store.put(_mid(1), b"old", audience="public")
    real_write = store._write
    calls = 0

    def full_once(match_id: str, body: bytes, now: float) -> Path:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_write(match_id, body, now)

    monkeypatch.setattr(store, "_write", full_once)
    clock.now += 1
    store.put(_mid(2), b"new", audience="public")
    assert store.get(_mid(2)) is not None
    assert store.get(_mid(1)) is None  # evicted to make room


def test_a_future_date_is_fixed_on_disk(tmp_path: Path) -> None:
    from arena.server.transcript_store import FUTURE_SLACK_S

    clock = Clock()
    FileTranscriptStore(tmp_path, RetentionPolicy(ttl_s=1000), time_fn=clock).put(
        MID, b"{}", audience="public"
    )
    clock.now -= FUTURE_SLACK_S + 10_000  # the clock stepped back
    FileTranscriptStore(tmp_path, RetentionPolicy(ttl_s=1000), time_fn=clock)  # re-dates
    clock.now += 1000
    # A later restart sees the corrected date, so the TTL runs out.
    reopened = FileTranscriptStore(tmp_path, RetentionPolicy(ttl_s=1000), time_fn=clock)
    assert reopened.get(MID) is None


def test_a_get_racing_a_replace_finds_the_new_record(tmp_path: Path, monkeypatch) -> None:
    store = FileTranscriptStore(tmp_path, time_fn=Clock())
    store.put(MID, b"old", audience="public")
    real_read = Path.read_bytes
    raced = False

    def read_bytes(self: Path) -> bytes:
        nonlocal raced
        if not raced:
            raced = True
            store.put(MID, b"new", audience="public")  # replaces and deletes the old file
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    got = store.get(MID)
    assert got is not None and got.body == b"new"
