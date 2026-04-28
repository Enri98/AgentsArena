"""Tests for OllamaClient HTTP wrapper."""

from __future__ import annotations

import json
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from arena.agents.ollama.client import OllamaClient
from arena.agents.ollama.exceptions import OllamaUnavailableError


def _fake_response(data: dict) -> MagicMock:
    body = json.dumps(data).encode("utf-8")
    response = MagicMock()
    response.read.return_value = body
    response.__enter__ = lambda s: s
    response.__exit__ = MagicMock(return_value=False)
    return response


def test_chat_posts_expected_body_and_returns_parsed_json() -> None:
    client = OllamaClient(host="http://localhost:11434")
    expected_response = {"message": {"role": "assistant", "content": '{"column": 0}'}}

    fake = _fake_response(expected_response)
    with patch("urllib.request.urlopen", return_value=fake) as mock_open:
        result = client.chat(
            model="llama3.2",
            messages=[{"role": "user", "content": "pick a column"}],
            format_spec={"type": "object", "properties": {"column": {"type": "integer"}}},
            seed=42,
            temperature=0.0,
        )

    assert result == expected_response
    call_args = mock_open.call_args
    request = call_args[0][0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["model"] == "llama3.2"
    assert body["stream"] is False
    assert body["options"]["seed"] == 42
    assert body["options"]["temperature"] == 0.0
    assert "format" in body


def test_chat_omits_format_when_none() -> None:
    client = OllamaClient()
    expected_response = {"message": {"role": "assistant", "content": "hi"}}

    with patch("urllib.request.urlopen", return_value=_fake_response(expected_response)):
        with patch("urllib.request.Request") as mock_req:
            mock_req.return_value.data = json.dumps({}).encode()
            client.chat(
                model="llama3.2",
                messages=[],
                format_spec=None,
                seed=0,
                temperature=0.0,
            )

    fake2 = _fake_response(expected_response)
    with patch("urllib.request.urlopen", return_value=fake2) as mock_open:
        client.chat(model="x", messages=[], format_spec=None, seed=0, temperature=0.0)
        request = mock_open.call_args[0][0]
        body = json.loads(request.data.decode("utf-8"))
        assert "format" not in body


def test_list_tags_returns_model_names() -> None:
    client = OllamaClient()
    fake_data = {"models": [{"name": "llama3.2:latest"}, {"name": "qwen2.5:1.5b"}]}

    with patch("urllib.request.urlopen", return_value=_fake_response(fake_data)):
        names = client.list_tags()

    assert names == ["llama3.2:latest", "qwen2.5:1.5b"]


def test_list_tags_empty_models() -> None:
    client = OllamaClient()
    fake_data: dict = {"models": []}

    with patch("urllib.request.urlopen", return_value=_fake_response(fake_data)):
        names = client.list_tags()

    assert names == []


def test_chat_url_error_raises_ollama_unavailable() -> None:
    client = OllamaClient(host="http://localhost:11434")

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
        with pytest.raises(OllamaUnavailableError) as exc_info:
            client.chat(model="x", messages=[], format_spec=None, seed=0, temperature=0.0)

    assert "localhost:11434" in str(exc_info.value)


def test_list_tags_url_error_raises_ollama_unavailable() -> None:
    client = OllamaClient(host="http://custom:9999")

    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
        with pytest.raises(OllamaUnavailableError) as exc_info:
            client.list_tags()

    assert "custom:9999" in str(exc_info.value)
