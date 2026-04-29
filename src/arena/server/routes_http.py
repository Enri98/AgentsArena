"""FastAPI HTTP router: POST /matches, GET /matches/{id}, GET /games, GET /schemas/payloads."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from arena.server.config import (
    DEFAULT_DISCONNECT_GRACE_MS,
    DEFAULT_PER_ACTION_RETRY_BUDGET,
    DEFAULT_PER_TURN_DEADLINE_MS,
    GAME_SCHEMA_VERSION,
    MAX_DISCONNECT_GRACE_MS,
    MAX_PER_TURN_DEADLINE_MS,
    RETRY_BUDGET_MAX,
    RETRY_BUDGET_MIN,
    WIRE_SCHEMA_VERSION,
)
from arena.server.errors import InvalidConfig, InvalidRequest, MatchNotFound, UnknownGame
from arena.server.payload_schemas import get_payload_schemas
from arena.server.registry import MatchRegistry

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class PlayerSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str | None = None


class CreateMatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    game_id: str = Field(min_length=1)
    game_config: dict[str, Any] | None = None
    players: list[PlayerSpec] = Field(default_factory=list)
    per_turn_deadline_ms: int = Field(default=DEFAULT_PER_TURN_DEADLINE_MS)
    per_action_retry_budget: int = Field(default=DEFAULT_PER_ACTION_RETRY_BUDGET)
    disconnect_grace_ms: int = Field(default=DEFAULT_DISCONNECT_GRACE_MS)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error_response(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


def _validate_range(value: int, lo: int, hi: int, field_name: str) -> None:
    if value < lo or value > hi:
        raise InvalidRequest(
            f"'{field_name}' must be between {lo} and {hi}, got {value}."
        )


# ---------------------------------------------------------------------------
# POST /matches
# ---------------------------------------------------------------------------


@router.post("/matches", status_code=201)
async def create_match_handler(request: Request) -> JSONResponse:
    try:
        raw = await request.json()
    except Exception:
        return _error_response(400, "invalid_request", "Request body is not valid JSON.")

    if not isinstance(raw, dict) or "game_id" not in raw:
        return _error_response(400, "invalid_request", "Missing required field 'game_id'.")

    try:
        body = CreateMatchRequest.model_validate(raw)
    except ValidationError as exc:
        return _error_response(400, "invalid_request", str(exc))

    try:
        _validate_range(
            body.per_turn_deadline_ms, 1, MAX_PER_TURN_DEADLINE_MS, "per_turn_deadline_ms"
        )
        _validate_range(
            body.per_action_retry_budget,
            RETRY_BUDGET_MIN,
            RETRY_BUDGET_MAX,
            "per_action_retry_budget",
        )
        _validate_range(
            body.disconnect_grace_ms, 1, MAX_DISCONNECT_GRACE_MS, "disconnect_grace_ms"
        )
    except InvalidRequest as exc:
        return _error_response(400, "invalid_request", exc.message)

    registry: MatchRegistry = request.app.state.match_registry

    try:
        match = registry.create(
            game_id=body.game_id,
            game_config_payload=body.game_config,
            players_spec=[p.model_dump() for p in body.players],
            per_turn_deadline_ms=body.per_turn_deadline_ms,
            per_action_retry_budget=body.per_action_retry_budget,
            disconnect_grace_ms=body.disconnect_grace_ms,
        )
    except UnknownGame as exc:
        return _error_response(400, exc.error_code, exc.message)
    except InvalidConfig as exc:
        details = exc.details if exc.details is not None else {}
        return _error_response(400, exc.error_code, exc.message, details=details)
    except Exception as exc:
        return _error_response(500, "server_error", str(exc))

    host = request.headers.get("host", "localhost")
    seat_0_url = f"ws://{host}/matches/{match.match_id}/play?seat=0"
    seat_1_url = f"ws://{host}/matches/{match.match_id}/play?seat=1"

    return JSONResponse(
        status_code=201,
        content={
            "match_id": match.match_id,
            "game_id": match.game_id,
            "game_schema_version": GAME_SCHEMA_VERSION,
            "schema_version": WIRE_SCHEMA_VERSION,
            "lifecycle": match.session.lifecycle.value,
            "per_turn_deadline_ms": match.per_turn_deadline_ms,
            "per_action_retry_budget": match.per_action_retry_budget,
            "disconnect_grace_ms": match.disconnect_grace_ms,
            "seat_0_url": seat_0_url,
            "seat_1_url": seat_1_url,
        },
    )


# ---------------------------------------------------------------------------
# GET /matches/{match_id}
# ---------------------------------------------------------------------------


@router.get("/matches/{match_id}")
def get_match(match_id: str, request: Request) -> JSONResponse:
    registry: MatchRegistry = request.app.state.match_registry

    try:
        match = registry.get(match_id)
    except MatchNotFound as exc:
        return _error_response(404, exc.error_code, exc.message)

    session = match.session
    local_match = session.local_match

    current_seat = None
    turn_count = 0
    if local_match is not None:
        turn_count = len(local_match.turns)
        if not local_match.rules_engine.is_terminal(local_match.state):
            current_seat = local_match.rules_engine.current_seat(local_match.state)

    players_out = [
        {"player_id": p.player_id, "label": p.label, "seat": p.seat}
        for p in match.players
    ]

    abort_out = None
    if session.abort is not None:
        abort_out = {
            "reason": session.abort.reason.value,
            "message": session.abort.message,
        }

    return JSONResponse(
        status_code=200,
        content={
            "match_id": match.match_id,
            "game_id": match.game_id,
            "lifecycle": session.lifecycle.value,
            "schema_version": WIRE_SCHEMA_VERSION,
            "current_seat": current_seat,
            "turn_count": turn_count,
            "players": players_out,
            "result": None,
            "abort": abort_out,
        },
    )


# ---------------------------------------------------------------------------
# GET /games
# ---------------------------------------------------------------------------


@router.get("/games")
def list_games(request: Request) -> JSONResponse:
    registry: MatchRegistry = request.app.state.match_registry
    game_registry = registry._game_registry

    games_out = []
    for definition in game_registry.list():
        config_schema = definition.config_type.model_json_schema()
        games_out.append(
            {
                "game_id": definition.game_id,
                "game_schema_version": GAME_SCHEMA_VERSION,
                "config_schema": config_schema,
                "min_seats": 2,
                "max_seats": 2,
            }
        )

    return JSONResponse(status_code=200, content={"games": games_out})


# ---------------------------------------------------------------------------
# GET /schemas/payloads
# ---------------------------------------------------------------------------


@router.get("/schemas/payloads")
def get_schemas_payloads() -> JSONResponse:
    return JSONResponse(status_code=200, content=get_payload_schemas())
