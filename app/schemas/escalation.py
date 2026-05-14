"""Escalation schemas for Heron Escalate.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass
class EscalationChannel:
    """Provides EscalationChannel behavior using local state or integrations and exposes structured outputs for callers."""

    name: str
    target: str


@dataclass
class EscalationEvent:
    """Provides EscalationEvent behavior using local state or integrations and exposes structured outputs for callers."""

    event_id: str
    channel: EscalationChannel
    created_at: datetime
    message: str
    severity: str = "info"
    service: str = "unknown"
    incident_key: Optional[str] = None
    metadata: Dict[str, object] = field(default_factory=dict)


@dataclass
class EscalationRequest:
    """Provides EscalationRequest behavior using local state or integrations and exposes structured outputs for callers."""

    service: str
    severity: str
    summary: str
    channels: List[EscalationChannel]
    decision_id: Optional[str] = None
    policy_allows: bool = True
    recovered: bool = False
    dedupe_window_seconds: int = 900
    metadata: Dict[str, object] = field(default_factory=dict)


def create_escalation(
    channel_name: str,
    target: str,
    message: str,
    *,
    severity: str = "info",
    service: str = "unknown",
    incident_key: Optional[str] = None,
    metadata: Optional[Dict[str, object]] = None,
) -> EscalationEvent:
    """Creates escalation using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    channel = EscalationChannel(name=channel_name, target=target)
    return EscalationEvent(
        event_id=f"esc-{int(datetime.utcnow().timestamp())}",
        channel=channel,
        created_at=datetime.utcnow(),
        message=message,
        severity=severity,
        service=service,
        incident_key=incident_key,
        metadata=metadata or {},
    )