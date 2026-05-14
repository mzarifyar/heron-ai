"""Audit/event schemas for Heron Explain.

"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
import uuid


@dataclass
class AuditEvent:
    """Provides AuditEvent behavior using local state or integrations and exposes structured outputs for callers."""

    event_id: str
    component: str
    event_type: str
    message: str
    created_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)
    correlation_ids: Dict[str, str] = field(default_factory=dict)
    signal_id: Optional[str] = None


def create_audit_event(
    component: str,
    event_type: str,
    message: str,
    *,
    metadata: Optional[Dict[str, Any]] = None,
    correlation_ids: Optional[Dict[str, str]] = None,
    signal_id: Optional[str] = None,
) -> AuditEvent:
    """Creates audit event using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return AuditEvent(
        event_id=f"audit-{uuid.uuid4().hex[:12]}",
        component=component,
        event_type=event_type,
        message=message,
        created_at=datetime.utcnow(),
        metadata=metadata or {},
        correlation_ids=correlation_ids or {},
        signal_id=signal_id,
    )


def audit_event_to_dict(event: AuditEvent) -> Dict[str, Any]:
    """Builds audit event to dict using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    payload = asdict(event)
    payload["created_at"] = event.created_at.isoformat()
    return payload