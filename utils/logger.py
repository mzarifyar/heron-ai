"""Centralized logging helper for Cortex."""

from __future__ import annotations

import datetime
from typing import Any, Literal

LogLevel = Literal["debug", "info", "error"]

_ALLOWED_LEVELS: tuple[LogLevel, ...] = ("debug", "info", "error")


def _normalize_level(level: str) -> LogLevel:
    """Normalizes level using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    normalized = level.lower()
    if normalized not in _ALLOWED_LEVELS:
        raise ValueError(f"Unsupported log level '{level}'. Expected one of {_ALLOWED_LEVELS}.")
    return normalized  # type: ignore[return-value]


def _current_log_level() -> str:
    """Builds current log level using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        from utils.settings import get_log_level  # Local import to avoid circular dependency
        level = get_log_level()
    except Exception:
        level = "info"
    return (level or "info").lower()


def _should_emit(level: LogLevel) -> bool:
    """Determines emit using local writes or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
    configured = _current_log_level()
    if configured not in ("debug", "info"):
        configured = "info"

    if level == "error":
        return True

    if level == "info":
        return configured in ("info", "debug")

    # level == "debug"
    return configured == "debug"


def _format_message(message: str, *args: Any, **kwargs: Any) -> str:
    """Formats message using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    if args or kwargs:
        try:
            return message.format(*args, **kwargs)
        except (KeyError, ValueError, IndexError):
            return f"{message} args={args} kwargs={kwargs}"
    return message


def log(level: LogLevel, message: str, *args: Any, **kwargs: Any) -> None:
    """Builds log using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""

    normalized_level = _normalize_level(level)
    if not _should_emit(normalized_level):
        return

    timestamp = datetime.datetime.now().isoformat()
    formatted_message = _format_message(message, *args, **kwargs)
    print(f"[{normalized_level.upper()} {timestamp}] {formatted_message}", flush=True)


def debug_log(message: str, *args: Any, **kwargs: Any) -> None:
    """Builds debug log using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""

    try:
        log("debug", message, *args, **kwargs)
    except Exception:
        # Avoid import loops or format errors during shutdown.
        pass
