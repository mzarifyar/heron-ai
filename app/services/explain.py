"""Explain service with in-memory traces and append-only audit log persistence.

"""

from __future__ import annotations
from app.core.paths import data as _dat

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Deque, Dict, List, Optional

from ..core import get_logger
from ..schemas.audit import AuditEvent, audit_event_to_dict, create_audit_event
from .chronicle import chronicle_service

logger = get_logger(__name__)


@dataclass
class ExplainEvent:
    """Provides ExplainEvent behavior using local state or integrations and exposes structured outputs for callers."""
    event_id: str
    component: str
    event_type: str
    message: str
    metadata: Dict[str, object] = field(default_factory=dict)
    correlation_ids: Dict[str, str] = field(default_factory=dict)
    signal_id: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class ExplainService:
    """Provides ExplainService behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, max_events: int = 1000, audit_path: str = _dat("explain.log")) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._events: Deque[ExplainEvent] = deque(maxlen=max_events)
        self._audit_events: Deque[AuditEvent] = deque(maxlen=max_events)
        self._audit_path = Path(audit_path)
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)

    def record_event(
        self,
        *,
        component: str,
        event_type: str,
        message: str,
        metadata: Optional[Dict[str, object]] = None,
        correlation_ids: Optional[Dict[str, str]] = None,
        signal_id: Optional[str] = None,
    ) -> None:
        """Records event using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        audit_event = create_audit_event(
            component,
            event_type,
            message,
            metadata=metadata or {},
            correlation_ids=correlation_ids or {},
            signal_id=signal_id,
        )
        event = ExplainEvent(
            event_id=audit_event.event_id,
            component=component,
            event_type=event_type,
            message=message,
            metadata=metadata or {},
            correlation_ids=correlation_ids or {},
            signal_id=signal_id,
            created_at=audit_event.created_at,
        )
        self._events.append(event)
        self._audit_events.append(audit_event)
        try:
            with self._audit_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(audit_event_to_dict(audit_event), ensure_ascii=True) + "\n")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to persist explain audit event", extra={"error": str(exc)})
        logger.info(
            "Explain event recorded",
            extra={
                "component": component,
                "event_type": event_type,
                "signal_id": signal_id,
                "event_id": audit_event.event_id,
            },
        )
        try:
            chronicle_service.ingest_component_event(
                component="explain",
                event_type=event_type,
                summary=message,
                metadata={
                    "source_component": component,
                    **(metadata or {}),
                },
                correlation_ids=correlation_ids or {},
                signal_id=signal_id,
                severity=str((metadata or {}).get("severity", "info")),
                tags=["explain", component],
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Failed to emit explain event to Chronicle",
                extra={"error": str(exc), "event_type": event_type},
            )

    def list_events(self) -> List[ExplainEvent]:
        """Lists events using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        return list(self._events)

    def list_audit_events(self, *, correlation_id: Optional[str] = None, limit: int = 100) -> List[AuditEvent]:
        """Lists audit events using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        events = list(self._audit_events)
        if correlation_id:
            events = [
                event
                for event in events
                if correlation_id in event.correlation_ids.values()
            ]
        return events[-limit:]

    def clear(self) -> None:
        """Clears the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._events.clear()
        self._audit_events.clear()
        try:
            if self._audit_path.exists():
                self._audit_path.unlink()
        except Exception:  # pragma: no cover - defensive
            pass


explain_service = ExplainService()