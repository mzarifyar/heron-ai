"""Signal-level utilities shared across ingestion and mitigation services.

"""

from __future__ import annotations

from datetime import datetime
from typing import Mapping


class SignalKey:
    """Provides SignalKey behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, service: str, component: str, kind: str) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.service = service
        self.component = component
        self.kind = kind

    def __repr__(self) -> str:  # pragma: no cover - trivial
        """Handles repr protocol behavior using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        return f"SignalKey(service={self.service}, component={self.component}, kind={self.kind})"

    def as_dict(self) -> Mapping[str, str]:
        """Builds as dict using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        return {"service": self.service, "component": self.component, "kind": self.kind}


def normalize_detected_at(value: str | datetime) -> datetime:
    """Normalizes detected at using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value.replace("Z", "+00:00"))