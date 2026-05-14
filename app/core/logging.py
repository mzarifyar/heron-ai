"""Centralized logging configuration for Heron.

"""

from __future__ import annotations

import logging
import sys
from typing import Any, Dict

from pythonjsonlogger import jsonlogger

from .config import get_settings


def configure_logging() -> None:
    """Builds configure logging using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    settings = get_settings()

    log_handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s %(environment)s %(region)s"
    )
    log_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(settings.log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(log_handler)

    logging.LoggerAdapter(
        root_logger,
        extra={"environment": settings.environment, "region": settings.region},
    )


def get_logger(name: str) -> logging.Logger:
    """Gets logger using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    settings = get_settings()
    logger = logging.getLogger(name)
    if not logger.handlers:
        configure_logging()

    extra: Dict[str, Any] = {
        "environment": settings.environment,
        "region": settings.region,
    }
    return logging.LoggerAdapter(logger, extra)  # type: ignore[return-value]
