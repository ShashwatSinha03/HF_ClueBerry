from __future__ import annotations

import json

import httpx
import pytest
from clueberry.analysis import (
    ModelResponseError,
    ModelTimeoutError,
    ModelUnavailableError,
    OllamaProvider,
)

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}}


def _provider(handler, **kwargs: object) -> OllamaProvider:
    return OllamaProvider("qwen3:4b", transport=httpx.MockTransport(handler), **kwargs)


def test_generate_json_sends_structured_request_and_returns_content() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": '{"ok":1}'}})

    content = _provider(handler, num_ctx=8192).generate_json("sys", "user", SCHEMA)

    payload = seen["payload"]
    assert content == '{"ok":1}'
    assert seen["url"] == "http://localhost:11434/api/chat"
    assert payload["model"] == "qwen3:4b"
    assert payload["stream"] is False
    assert payload["format"] == SCHEMA
    assert payload["options"] == {"temperature": 0, "num_ctx": 8192}
    assert payload["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "user"},
    ]
    assert "think" not in payload


def test_think_setting_is_sent_only_when_configured() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": "{}"}})

    _provider(handler, think=False).generate_json("s", "p", SCHEMA)
    assert seen["think"] is False


def test_missing_model_is_reported_as_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "model 'qwen3:4b' not found"})

    with pytest.raises(ModelUnavailableError, match="ollama pull qwen3:4b"):
        _provider(handler).generate_json("s", "p", SCHEMA)


def test_server_error_is_a_response_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(ModelResponseError, match="HTTP 500"):
        _provider(handler).generate_json("s", "p", SCHEMA)


def test_connection_failure_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(ModelUnavailableError, match="ollama serve"):
        _provider(handler).generate_json("s", "p", SCHEMA)


def test_timeout_is_reported() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow")

    with pytest.raises(ModelTimeoutError):
        _provider(handler).generate_json("s", "p", SCHEMA)


@pytest.mark.parametrize(
    "body",
    [{"unexpected": True}, {"message": {"content": 42}}, {"message": "nope"}],
)
def test_unexpected_response_shape(body: dict[str, object]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with pytest.raises(ModelResponseError):
        _provider(handler).generate_json("s", "p", SCHEMA)


def test_non_json_response_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not ollama</html>")

    with pytest.raises(ModelResponseError):
        _provider(handler).generate_json("s", "p", SCHEMA)


@pytest.mark.parametrize("installed", ["qwen3:4b", "qwen3:4b:latest"])
def test_ensure_available_accepts_installed_model(installed: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": installed, "model": installed}]})

    _provider(handler).ensure_available()


def test_ensure_available_rejects_missing_model() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"models": [{"name": "gemma3:1b", "model": "gemma3:1b"}]})

    with pytest.raises(ModelUnavailableError, match="not installed"):
        _provider(handler).ensure_available()


def test_ensure_available_reports_unreachable_server() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(ModelUnavailableError):
        _provider(handler).ensure_available()


@pytest.mark.parametrize("url", ["localhost:11434", "ftp://localhost", "http://"])
def test_rejects_invalid_base_url(url: str) -> None:
    with pytest.raises(ValueError):
        OllamaProvider("qwen3:4b", base_url=url)
