"""GET /matches/{id}/public-transcript status codes (Phase 40 Slice 2)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arena.server.app import create_app
from arena.server.rate_limits import RateLimiter
from arena.server.transcript_store import MemoryTranscriptStore, RetentionPolicy

MID = "Abc_def-0123456789xyzQ"
_MATCH = {"game_id": "tictactoe", "per_turn_deadline_ms": 2000, "disconnect_grace_ms": 500}


class _Clock:
    def __init__(self) -> None:
        self.now = 1_700_000_000.0

    def __call__(self) -> float:
        return self.now


def _app(**kwargs):  # type: ignore[no-untyped-def]
    kwargs.setdefault("rate_limiter", RateLimiter.unlimited())
    return create_app(**kwargs)


def test_a_stored_transcript_is_served_verbatim() -> None:
    store = MemoryTranscriptStore()
    store.put(MID, b'{"view": "public"}', audience="public")
    with TestClient(_app(transcript_store=store)) as client:
        resp = client.get(f"/matches/{MID}/public-transcript")
    assert resp.status_code == 200
    assert resp.content == b'{"view": "public"}'
    assert resp.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize("match_id", ["unknown-but-valid", "a.b", "x" * 65, "%2E%2E"])
def test_an_unknown_or_malformed_id_is_404(match_id: str) -> None:
    with TestClient(_app()) as client:
        resp = client.get(f"/matches/{match_id}/public-transcript")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "match_not_found"


def test_a_live_match_is_409_until_it_ends() -> None:
    app = _app()
    with TestClient(app) as client:
        match_id = client.post("/matches", json=_MATCH).json()["match_id"]
        resp = client.get(f"/matches/{match_id}/public-transcript")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "transcript_not_ready"
        # Settled without a stored transcript (the store refused it): 404.
        app.state.match_registry.get(match_id).transcript_settled = True
        assert client.get(f"/matches/{match_id}/public-transcript").status_code == 404


def test_an_expired_transcript_is_404() -> None:
    clock = _Clock()
    store = MemoryTranscriptStore(RetentionPolicy(ttl_s=60), time_fn=clock)
    store.put(MID, b"{}", audience="public")
    with TestClient(_app(transcript_store=store)) as client:
        assert client.get(f"/matches/{MID}/public-transcript").status_code == 200
        clock.now += 60
        assert client.get(f"/matches/{MID}/public-transcript").status_code == 404


def test_reads_are_rate_limited() -> None:
    app = _app(rate_limiter=RateLimiter(max_transcript_reads_per_ip_per_min=2))
    with TestClient(app) as client:
        codes = [client.get(f"/matches/{MID}/public-transcript").status_code for _ in range(3)]
    assert codes == [404, 404, 429]


def test_the_app_closes_its_store_on_shutdown() -> None:
    closed = []

    class Tracking(MemoryTranscriptStore):
        def close(self) -> None:
            closed.append(True)
            super().close()

    with TestClient(_app(transcript_store=Tracking())):
        pass
    assert closed == [True]


def test_error_responses_are_not_cacheable() -> None:
    with TestClient(_app()) as client:
        resp = client.get(f"/matches/{MID}/public-transcript")
    assert resp.status_code == 404
    assert resp.headers["cache-control"] == "private, no-store"


def test_a_save_finishing_between_the_checks_is_not_a_404() -> None:
    # The pending flag is read first; the store then has the record.
    app = _app()

    class SavesDuringGet(MemoryTranscriptStore):
        def get(self, match_id: str):  # type: ignore[no-untyped-def]
            match = app.state.match_registry.get(match_id)
            if not match.transcript_settled:
                self.put(match_id, b'{"late": true}', audience="public")
                match.transcript_settled = True
            return super().get(match_id)

    app.state.transcript_store = SavesDuringGet()
    with TestClient(app) as client:
        match_id = client.post("/matches", json=_MATCH).json()["match_id"]
        resp = client.get(f"/matches/{match_id}/public-transcript")
    assert resp.status_code == 200


@pytest.mark.parametrize(
    ("game_id", "config"),
    [
        ("connect4", {"rows": 21, "columns": 7}),
        ("connect4", {"rows": 6, "columns": 500}),
        ("nim", {"num_piles": 1000, "max_pile_size": 1}),
        ("nim", {"num_piles": 3, "max_pile_size": 101}),
    ],
)
def test_board_sizes_are_bounded(game_id: str, config: dict) -> None:
    # An unbounded board made one match's stored transcript as large as a
    # client liked.
    with TestClient(_app()) as client:
        resp = client.post("/matches", json={"game_id": game_id, "game_config": config})
    assert resp.status_code == 400
