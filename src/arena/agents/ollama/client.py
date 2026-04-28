"""Stdlib HTTP client wrapping the Ollama REST API."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from arena.agents.ollama.exceptions import OllamaServerError, OllamaUnavailableError


class OllamaClient:
    """Minimal synchronous client for the Ollama local inference API."""

    def __init__(
        self,
        host: str = "http://localhost:11434",
        timeout: float = 30.0,
    ) -> None:
        self.host = host.rstrip("/")
        self.timeout = timeout

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        format_spec: dict[str, Any] | None,
        seed: int,
        temperature: float,
    ) -> dict[str, Any]:
        """POST /api/chat and return the parsed response dict."""

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {"seed": seed, "temperature": temperature},
        }
        if format_spec is not None:
            body["format"] = format_spec

        return self._post("/api/chat", body)

    def list_tags(self) -> list[str]:
        """GET /api/tags and return the list of model name strings."""

        data = self._get("/api/tags")
        models: list[dict[str, Any]] = data.get("models", [])
        return [m["name"] for m in models]

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        url = self.host + path
        payload = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._send(request)

    def _get(self, path: str) -> dict[str, Any]:
        url = self.host + path
        request = urllib.request.Request(url, method="GET")
        return self._send(request)

    def _send(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise OllamaServerError(
                self.host, exc.code, _read_error_body(exc)
            ) from exc
        except urllib.error.URLError as exc:
            raise OllamaUnavailableError(self.host, str(exc.reason)) from exc


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return exc.reason if isinstance(exc.reason, str) else str(exc.reason)
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw.strip() or (
            exc.reason if isinstance(exc.reason, str) else str(exc.reason)
        )
    if isinstance(parsed, dict) and "error" in parsed:
        return str(parsed["error"])
    return raw.strip()


__all__: tuple[str, ...] = ("OllamaClient",)
