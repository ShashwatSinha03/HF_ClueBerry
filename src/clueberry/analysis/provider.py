from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx


class AnalysisError(RuntimeError):
    """Base class for claim-analysis failures."""


class ModelUnavailableError(AnalysisError):
    """The model server can't be reached, or the model isn't installed."""


class ModelTimeoutError(AnalysisError):
    """The model didn't answer within the configured timeout."""


class ModelResponseError(AnalysisError):
    """The model answered, but not with usable output."""


class ModelProvider(Protocol):
    """The only interface the analyzer uses, so the model/runtime stays swappable."""

    @property
    def name(self) -> str: ...

    def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        """Return the model's raw text answer, asked to conform to `schema`."""
        ...


class OllamaProvider:
    """Calls a local Ollama server's /api/chat endpoint with structured (JSON schema) output."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str = "http://localhost:11434",
        timeout: float = 300.0,
        num_ctx: int = 16384,
        think: bool | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        parts = urlsplit(base_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"Invalid Ollama base URL: {base_url!r}")
        self.model = model
        self._base_url = base_url
        self._num_ctx = num_ctx
        self._think = think
        # trust_env=False: never route repository content through proxies
        # configured in the environment.
        self._client = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            transport=transport,
            follow_redirects=False,
            trust_env=False,
        )

    @property
    def name(self) -> str:
        return f"ollama/{self.model}"

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> OllamaProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return self._client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise ModelTimeoutError(f"Ollama did not respond in time ({exc})") from exc
        except httpx.RequestError as exc:
            raise ModelUnavailableError(
                f"Cannot reach Ollama at {self._base_url} ({exc}). Is `ollama serve` running?"
            ) from exc

    def ensure_available(self) -> None:
        """Fail fast, before any slow work, if the server or model is missing."""
        response = self._request("GET", "/api/tags")
        if response.status_code != 200:
            raise ModelUnavailableError(
                f"Ollama returned HTTP {response.status_code} for /api/tags"
            )
        try:
            models = response.json().get("models", [])
            names = {m.get("name") for m in models} | {m.get("model") for m in models}
        except (ValueError, AttributeError, TypeError) as exc:
            raise ModelResponseError("Unexpected response from Ollama /api/tags") from exc
        if self.model not in names and f"{self.model}:latest" not in names:
            raise ModelUnavailableError(
                f"Model {self.model!r} is not installed in Ollama. Run: ollama pull {self.model}"
            )

    def generate_json(self, system: str, prompt: str, schema: dict[str, Any]) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0, "num_ctx": self._num_ctx},
        }
        if self._think is not None:
            payload["think"] = self._think

        response = self._request("POST", "/api/chat", json=payload)
        if response.status_code == 404:
            raise ModelUnavailableError(
                f"Model {self.model!r} not found in Ollama. Run: ollama pull {self.model}"
            )
        if response.status_code >= 400:
            raise ModelResponseError(
                f"Ollama returned HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            content = response.json()["message"]["content"]
        except (ValueError, KeyError, TypeError) as exc:
            raise ModelResponseError("Unexpected response shape from Ollama /api/chat") from exc
        if not isinstance(content, str):
            raise ModelResponseError("Ollama returned non-text message content")
        return content
