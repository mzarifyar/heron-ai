"""Configuration utilities for Heron."""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from .paths import config as _cfg, data as _dat, PROJECT_ROOT


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = Field("heron", env="HERON_APP_NAME")
    environment: str = Field("local", env="HERON_ENV")
    region: str = Field("us-east-1", env="HERON_REGION")
    api_host: str = Field("0.0.0.0", env="HERON_API_HOST")
    api_port: int = Field(8080, env="HERON_API_PORT")
    log_level: str = Field("INFO", env="HERON_LOG_LEVEL")
    telemetry_buffer_size: int = Field(512, env="HERON_TELEMETRY_BUFFER_SIZE")
    ingest_auth_token: Optional[str] = Field(None, env="HERON_INGEST_TOKEN")

    thresholds_path: str       = Field(default_factory=lambda: _cfg("thresholds.json"),       env="HERON_THRESHOLDS_PATH")
    alarm_guard_script: str    = Field(default_factory=lambda: str(PROJECT_ROOT / "tools" / "get_alarm_status.py"), env="HERON_ALARM_GUARD_SCRIPT")
    pullers_config_path: str   = Field(default_factory=lambda: _cfg("pullers.yaml"),          env="HERON_PULLERS_CONFIG_PATH")
    pullers_state_path: str    = Field(default_factory=lambda: _dat("puller_state.json"),     env="HERON_PULLERS_STATE_PATH")
    local_db_path: str         = Field(default_factory=lambda: _dat("heron_local.db"),       env="HERON_LOCAL_DB_PATH")
    jira_auth_store_path: str  = Field(default_factory=lambda: _dat("jira_auth.json"),        env="HERON_JIRA_AUTH_STORE_PATH")

    alarm_guard_enabled: bool      = Field(False, env="HERON_ALARM_GUARD_ENABLED")
    alarm_guard_drop_ok: bool      = Field(False, env="HERON_ALARM_GUARD_DROP_OK")
    alarm_guard_timeout: int       = Field(45, env="HERON_ALARM_GUARD_TIMEOUT")
    pullers_scheduler_enabled: Optional[bool] = Field(None, env="HERON_PULLERS_SCHEDULER_ENABLED")
    jira_browser_auth_url: str     = Field("https://your-jira-instance.atlassian.net", env="HERON_JIRA_BROWSER_AUTH_URL")
    demo_mode: bool                = Field(False, env="HERON_DEMO_MODE")

    @validator("log_level")
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError(f"Unsupported log level: {value}")
        return normalized


@lru_cache
def get_settings() -> Settings:
    return Settings()
