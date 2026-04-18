from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LoggingSettings(BaseSettings):
    log_level: str = Field(default="INFO", alias="AUTOSPIDER_LOG_LEVEL")
    log_json: bool = Field(default=False, alias="AUTOSPIDER_LOG_JSON")
    log_event_prefix: str = Field(default="autospider", alias="AUTOSPIDER_LOG_EVENT_PREFIX")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )
