from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for Clueberry, loaded from the environment."""

    model_config = SettingsConfigDict(
        env_prefix="CLUEBERRY_",
        env_file=".env",
        extra="ignore",
    )

    log_level: str = "INFO"
    github_token: str | None = None
    """Optional GitHub personal access token (CLUEBERRY_GITHUB_TOKEN).

    Unauthenticated access works for public issues/PRs but is subject to
    GitHub's lower, stricter rate limit; a token raises that limit.
    """

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:4b"
    ollama_timeout_seconds: float = 300.0
    """Per model call. qwen3:4b thinking-mode assessments measured 69-156 s on an
    Apple M3 Pro, with one exceeding 180 s."""
    ollama_num_ctx: int = 16384
    """Context window requested from Ollama; its own default is too small for evidence."""
    ollama_think: bool | None = None
    """Thinking mode for claim assessment. None leaves the model default (Qwen3: on).

    Measured with qwen3:4b: thinking gave correct verdicts on all benchmark claims,
    while thinking off produced wrong ones. Setting True errors on models
    without thinking support (e.g. gemma3), hence None rather than True.
    """
    ollama_extraction_think: bool | None = False
    """Thinking mode for claim extraction. Off by default: with qwen3:4b, thinking
    made extraction exceed the timeout, while thinking off was fast and reliable."""
