"""HTTP route tests using FastAPI TestClient (sync)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from arena.server.app import create_app

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    return TestClient(create_app(), raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# POST /matches — happy path
# ---------------------------------------------------------------------------


def test_post_matches_connect4_happy_path() -> None:
    client = _client()
    resp = client.post(
        "/matches",
        json={
            "game_id": "connect4",
            "game_config": {"rows": 6, "columns": 7, "connect_length": 4},
            "players": [{"label": "alice"}, {"label": "bob"}],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert "match_id" in data
    assert data["game_id"] == "connect4"
    assert data["lifecycle"] == "created"
    assert data["schema_version"] == 1
    assert data["game_schema_version"] == 1
    assert "per_turn_deadline_ms" in data
    assert "per_action_retry_budget" in data
    assert "disconnect_grace_ms" in data
    assert "seat_0_url" in data
    assert "seat_1_url" in data

    mid = data["match_id"]
    assert mid in data["seat_0_url"]
    assert mid in data["seat_1_url"]
    assert "seat=0" in data["seat_0_url"]
    assert "seat=1" in data["seat_1_url"]
    assert data["seat_0_url"].startswith("ws://")
    assert data["seat_1_url"].startswith("ws://")


def test_post_matches_defaults_populated() -> None:
    client = _client()
    resp = client.post("/matches", json={"game_id": "connect4"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["per_turn_deadline_ms"] == 30000
    assert data["per_action_retry_budget"] == 3
    assert data["disconnect_grace_ms"] == 30000


# ---------------------------------------------------------------------------
# POST /matches — error cases
# ---------------------------------------------------------------------------


def test_post_matches_unknown_game() -> None:
    client = _client()
    resp = client.post("/matches", json={"game_id": "chess"})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "unknown_game"


def test_post_matches_invalid_config() -> None:
    client = _client()
    resp = client.post(
        "/matches",
        json={
            "game_id": "connect4",
            "game_config": {"rows": 1, "columns": 7, "connect_length": 4},
        },
    )
    assert resp.status_code == 400
    data = resp.json()
    assert data["error"]["code"] == "invalid_config"
    assert "details" in data["error"]


def test_post_matches_malformed_body_missing_game_id() -> None:
    client = _client()
    resp = client.post("/matches", json={"players": []})
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"


def test_post_matches_per_turn_deadline_zero() -> None:
    client = _client()
    resp = client.post(
        "/matches", json={"game_id": "connect4", "per_turn_deadline_ms": 0}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"


def test_post_matches_per_turn_deadline_exceeds_max() -> None:
    client = _client()
    resp = client.post(
        "/matches", json={"game_id": "connect4", "per_turn_deadline_ms": 999999999}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"


def test_post_matches_retry_budget_below_min() -> None:
    client = _client()
    resp = client.post(
        "/matches", json={"game_id": "connect4", "per_action_retry_budget": -1}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"


def test_post_matches_retry_budget_above_max() -> None:
    client = _client()
    resp = client.post(
        "/matches", json={"game_id": "connect4", "per_action_retry_budget": 11}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_request"


# ---------------------------------------------------------------------------
# GET /matches/{id}
# ---------------------------------------------------------------------------


def test_get_match_after_creation() -> None:
    client = _client()
    create_resp = client.post(
        "/matches",
        json={"game_id": "connect4", "players": [{"label": "a"}, {"label": "b"}]},
    )
    mid = create_resp.json()["match_id"]
    resp = client.get(f"/matches/{mid}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["match_id"] == mid
    assert data["lifecycle"] == "created"
    assert data["game_id"] == "connect4"
    assert isinstance(data["players"], list)
    assert len(data["players"]) == 2
    assert data["result"] is None


def test_get_match_not_found() -> None:
    client = _client()
    resp = client.get("/matches/no-such-match-id")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "match_not_found"


# ---------------------------------------------------------------------------
# GET /games
# ---------------------------------------------------------------------------


def test_get_games_includes_connect4_and_tictactoe() -> None:
    client = _client()
    resp = client.get("/games")
    assert resp.status_code == 200
    data = resp.json()
    game_ids = {g["game_id"] for g in data["games"]}
    assert "connect4" in game_ids
    assert "tictactoe" in game_ids


def test_get_games_config_schema_non_empty() -> None:
    client = _client()
    resp = client.get("/games")
    for game in resp.json()["games"]:
        assert game["config_schema"]
        assert isinstance(game["config_schema"], dict)


# ---------------------------------------------------------------------------
# GET /schemas/payloads
# ---------------------------------------------------------------------------

_REQUIRED_KEYS = {
    "ObservationRequestPayload",
    "ActionResponsePayload",
    "DomainErrorPayload",
    "RuntimeTranscriptPayload",
    "SessionStatusPayload",
    "RuntimeEventPayload",
    "PlayerRecordPayload",
    "AbortMetadataPayload",
    "Envelope",
}


def test_get_schemas_payloads_contains_required_keys() -> None:
    client = _client()
    resp = client.get("/schemas/payloads")
    assert resp.status_code == 200
    data = resp.json()
    assert data["schema_version"] == 1
    missing = _REQUIRED_KEYS - set(data["schemas"].keys())
    assert missing == set(), f"Missing payload keys: {missing}"


def test_get_schemas_payloads_byte_stable() -> None:
    client = _client()
    r1 = client.get("/schemas/payloads")
    r2 = client.get("/schemas/payloads")
    assert r1.content == r2.content
