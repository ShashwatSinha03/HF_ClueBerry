from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for Clueberry, loaded from the environment.

    Settings for model providers, etc. will be added in the sprints that
    introduce them.
    """

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
