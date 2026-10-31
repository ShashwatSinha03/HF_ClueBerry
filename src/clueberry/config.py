from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for Clueberry, loaded from the environment.

    Only foundation-level settings exist here. Settings for GitHub access,
    model providers, etc. will be added in the sprints that introduce them.
    """

    model_config = SettingsConfigDict(
        env_prefix="CLUEBERRY_",
        env_file=".env",
        extra="ignore",
    )

    log_level: str = "INFO"
