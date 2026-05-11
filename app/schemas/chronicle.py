"""Chronicle schemas for incident timelines and postmortems.

"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
import uuid

IncidentStatus = Literal["open", "resolved", "postmortem"]


@dataclass
class ChronicleTimelineEntry:
    """Provides ChronicleTimelineEntry behavior using local state or integrations and exposes structured outputs for callers."""

    event_id: str
    incident_id: str
    happened_at: datetime
    component: str
    event_type: str
    summary: str
    severity: str = "info"
    signal_id: Optional[str] = None
    decision_id: Optional[str] = None
    action_id: Optional[str] = None
    correlation_ids: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    near_miss: bool = False


@dataclass
class ChronicleAnnotation:
    """Provides ChronicleAnnotation behavior using local state or integrations and exposes structured outputs for callers."""

    annotation_id: str
    incident_id: str
    author: str
    note: str
    created_at: datetime
    tags: List[str] = field(default_factory=list)
    attachments: List[str] = field(default_factory=list)


@dataclass
class ChroniclePostmortem:
    """Provides ChroniclePostmortem behavior using local state or integrations and exposes structured outputs for callers."""

    postmortem_id: str
    incident_id: str
    template_version: str
    summary: str = ""
    impact: str = ""
    root_cause: str = ""
    timeline_summary: str = ""
    lessons_learned: List[str] = field(default_factory=list)
    follow_up_actions: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class ChronicleIncident:
    """Provides ChronicleIncident behavior using local state or integrations and exposes structured outputs for callers."""

    incident_id: str
    service: str
    environment: str
    region: str
    org_id: str = "default"
    status: IncidentStatus = "open"
    severity: str = "info"
    summary: str = ""
    started_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    linked_incidents: List[str] = field(default_factory=list)
    decision_ids: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass
class ChronicleReport:
    """Provides ChronicleReport behavior using local state or integrations and exposes structured outputs for callers."""

    incident_id: str
    created_at: datetime
    entries: List[ChronicleTimelineEntry] = field(default_factory=list)
    action_failure_rate: float = 0.0
    near_miss_count: int = 0
    tags: List[str] = field(default_factory=list)


def create_timeline_entry(
    incident_id: str,
    *,
    component: str,
    event_type: str,
    summary: str,
    severity: str = "info",
    signal_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    action_id: Optional[str] = None,
    correlation_ids: Optional[Dict[str, str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None,
    near_miss: bool = False,
) -> ChronicleTimelineEntry:
    """Creates timeline entry using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return ChronicleTimelineEntry(
        event_id=f"evt-{uuid.uuid4().hex[:12]}",
        incident_id=incident_id,
        happened_at=datetime.utcnow(),
        component=component,
        event_type=event_type,
        summary=summary,
        severity=severity,
        signal_id=signal_id,
        decision_id=decision_id,
        action_id=action_id,
        correlation_ids=correlation_ids or {},
        metadata=metadata or {},
        tags=tags or [],
        near_miss=near_miss,
    )


def create_annotation(
    incident_id: str,
    *,
    author: str,
    note: str,
    tags: Optional[List[str]] = None,
    attachments: Optional[List[str]] = None,
) -> ChronicleAnnotation:
    """Creates annotation using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return ChronicleAnnotation(
        annotation_id=f"ann-{uuid.uuid4().hex[:12]}",
        incident_id=incident_id,
        author=author,
        note=note,
        created_at=datetime.utcnow(),
        tags=tags or [],
        attachments=attachments or [],
    )


def create_postmortem(
    incident_id: str,
    *,
    template_version: str = "v1",
) -> ChroniclePostmortem:
    """Creates postmortem using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    now = datetime.utcnow()
    return ChroniclePostmortem(
        postmortem_id=f"pm-{uuid.uuid4().hex[:12]}",
        incident_id=incident_id,
        template_version=template_version,
        created_at=now,
        updated_at=now,
    )


def create_report(incident_id: str) -> ChronicleReport:
    """Creates report using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return ChronicleReport(incident_id=incident_id, created_at=datetime.utcnow())


def chronicle_to_dict(value: Any) -> Dict[str, Any]:
    """Builds chronicle to dict using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    payload = asdict(value)
    for key, current in list(payload.items()):
        if isinstance(current, datetime):
            payload[key] = current.isoformat()
        elif isinstance(current, list):
            items = []
            for item in current:
                if hasattr(item, "__dataclass_fields__"):
                    items.append(chronicle_to_dict(item))
                else:
                    items.append(item)
            payload[key] = items
    return payload