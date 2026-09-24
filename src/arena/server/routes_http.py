"""FastAPI HTTP router: POST /matches, GET /matches/{id}, GET /games, GET /schemas/payloads."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
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
from arena.server.errors import (
    InvalidConfig,
    InvalidRequest,
    MatchNotFound,
    ServerBusy,
    UnknownGame,
)
from arena.server.payload_schemas import get_payload_schemas
from arena.server.rate_limits import RateLimiter, RateLimitExceeded
from arena.server.registry import MatchRegistry
from arena.server.transcript_store import TranscriptStore, is_valid_match_id

router = APIRouter()
logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


#: Largest POST /matches body. A create request is a few hundred bytes; the
#: body used to be read and parsed whole, however large, before any check.
MAX_CREATE_BODY_BYTES: int = 64 * 1024
MAX_PLAYER_LABEL_CHARS: int = 64


class PlayerSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str | None = Field(default=None, max_length=MAX_PLAYER_LABEL_CHARS)


class CreateMatchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    game_id: str = Field(min_length=1)
    game_config: dict[str, Any] | None = None
    # Two seats: every label is echoed in every welcome, so 50,000 of them were
    # an amplifier.
    players: list[PlayerSpec] = Field(default_factory=list, max_length=2)
    per_turn_deadline_ms: int = Field(default=DEFAULT_PER_TURN_DEADLINE_MS)
    per_action_retry_budget: int = Field(default=DEFAULT_PER_ACTION_RETRY_BUDGET)
    disconnect_grace_ms: int = Field(default=DEFAULT_DISCONNECT_GRACE_MS)
    #: Phase 38, optional: the wire versions the creating client can read. When
    #: given and the server's version is not among them, creation is refused
    #: with 400, not later at hello with 4400. Most important for a
    #: hidden-information game, which an older wire cannot serve without leaking.
    supported_schema_versions: list[int] | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _error_response(status: int, code: str, message: str, details: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(status_code=status, content=body)


def _client_ip(request: Request) -> str:
    """Best-effort source address for rate-limit bucketing.

    Behind a reverse proxy (the documented deployment shape) this is the proxy
    unless it is configured to forward the peer address; v1 does not trust
    ``X-Forwarded-For`` because nothing authenticates it.
    """

    client = request.client
    return client.host if client is not None else "unknown"


def _validate_range(value: int, lo: int, hi: int, field_name: str) -> None:
    if value < lo or value > hi:
        raise InvalidRequest(
            f"'{field_name}' must be between {lo} and {hi}, got {value}."
        )


# ---------------------------------------------------------------------------
# POST /matches
# ---------------------------------------------------------------------------


async def _read_capped_body(request: Request, limit: int) -> bytes | None:
    """The request body, or ``None`` once it exceeds ``limit`` bytes."""

    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > limit:
            return None
    return bytes(body)


@router.post("/matches", status_code=201)
async def create_match_handler(request: Request) -> JSONResponse:
    # The creation cap is checked before the body is read: a client already
    # over it used to have a 50 MB body read and parsed before the 429.
    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is not None:
        try:
            limiter.check_match_creation(ip=_client_ip(request))
        except RateLimitExceeded as exc:
            logger.warning(
                "rate_limited",
                schema_version=WIRE_SCHEMA_VERSION,
                scope=exc.scope,
                detail=exc.message,
            )
            return _error_response(429, "rate_limited", exc.message)

    body_bytes = await _read_capped_body(request, MAX_CREATE_BODY_BYTES)
    if body_bytes is None:
        return _error_response(
            413,
            "request_too_large",
            f"A create request is at most {MAX_CREATE_BODY_BYTES} bytes.",
        )
    try:
        raw = json.loads(body_bytes)
    except (ValueError, RecursionError):
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

    if (
        body.supported_schema_versions is not None
        and WIRE_SCHEMA_VERSION not in body.supported_schema_versions
    ):
        return _error_response(
            400,
            "schema_version_unsupported",
            f"This server speaks wire schema_version {WIRE_SCHEMA_VERSION}; the client "
            f"supports {body.supported_schema_versions}.",
        )

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
    except ServerBusy as exc:
        return _error_response(503, exc.error_code, exc.message)
    except Exception as exc:
        return _error_response(500, "server_error", str(exc))

    logger.info(
        "match_created",
        match_id=match.match_id,
        seat=None,
        schema_version=1,
        game_id=match.game_id,
    )

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
# GET /matches/{match_id}/public-transcript (Phase 40)
# ---------------------------------------------------------------------------


@router.get("/matches/{match_id}/public-transcript")
async def get_public_transcript(match_id: str, request: Request) -> Response:
    """The public transcript of an ended match.

    Exactly what a spectator received in ``match_finished`` / ``match_aborted``.
    Served from the transcript store, so it outlives the connections, the
    registry's retention, and (with a durable store) a restart. Nothing
    seat-scoped is ever served here: holding the ``match_id`` is not holding a
    seat.
    """

    limiter: RateLimiter | None = getattr(request.app.state, "rate_limiter", None)
    if limiter is not None:
        try:
            limiter.check_transcript_read(ip=_client_ip(request))
        except RateLimitExceeded as exc:
            return _error_response(429, "rate_limited", exc.message)

    store: TranscriptStore = request.app.state.transcript_store
    if is_valid_match_id(match_id):
        record = await asyncio.to_thread(store.get, match_id)
        if record is not None:
            return Response(
                content=record.body,
                media_type="application/json",
                # The URL is a capability: keep it out of shared caches.
                headers={"Cache-Control": "private, no-store"},
            )

        registry: MatchRegistry = request.app.state.match_registry
        try:
            match = registry.get(match_id)
        except MatchNotFound:
            match = None
        if match is not None and not match.transcript_settled:
            return _error_response(
                409,
                "transcript_not_ready",
                "The match has not ended, or its transcript is still being stored; "
                "retry after match_finished or match_aborted.",
            )

    return _error_response(
        404,
        "match_not_found",
        "No public transcript for this match: unknown id, expired, or never stored.",
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
