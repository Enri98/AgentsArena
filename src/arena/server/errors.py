"""Typed server-layer exceptions with HTTP status and wire error codes."""

from __future__ import annotations


class ServerError(Exception):
    """Base class for arena.server exceptions."""

    http_status: int = 500
    error_code: str = "server_error"

    def __init__(self, message: str, *, details: object = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class UnknownGame(ServerError):
    http_status = 400
    error_code = "unknown_game"


class InvalidConfig(ServerError):
    http_status = 400
    error_code = "invalid_config"


class InvalidRequest(ServerError):
    http_status = 400
    error_code = "invalid_request"


class MatchNotFound(ServerError):
    http_status = 404
    error_code = "match_not_found"
