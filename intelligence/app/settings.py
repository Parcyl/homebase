"""Environment-driven configuration. Loaded once at startup."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    # claude-sonnet-4-20250514 reached end-of-life 2026-06-15 (the API now 404s it).
    # Default to the current Sonnet; override with ANTHROPIC_MODEL.
    anthropic_model: str = Field(default="claude-sonnet-4-6", alias="ANTHROPIC_MODEL")

    # No HOMEBASE_ROOT env override -> fall back to the repo root (three levels up
    # from this file: app/ -> intelligence/ -> repo root).
    homebase_root: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent.parent.parent,
        alias="HOMEBASE_ROOT",
    )
    langgraph_host: str = Field(default="127.0.0.1", alias="LANGGRAPH_HOST")
    langgraph_port: int = Field(default=8080, alias="LANGGRAPH_PORT")

    log_level: str = Field(default="INFO", alias="LOG_LEVEL")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
