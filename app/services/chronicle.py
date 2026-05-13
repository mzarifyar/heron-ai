"""Chronicle service for immutable timeline storage and postmortem workflows.

"""

from __future__ import annotations
from app.core.paths import data as _dat

from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
from typing import Dict, List, Optional

from ..core import get_logger, get_settings
from ..schemas.chronicle import (
    ChronicleAnnotation,
    ChronicleIncident,
    ChroniclePostmortem,
    ChronicleReport,
    ChronicleTimelineEntry,
    chronicle_to_dict,
    create_annotation,
    create_postmortem,
    create_report,
    create_timeline_entry,
)

logger = get_logger(__name__)

_ANNOTATION_ROLES = {"admin", "operator", "sre"}
_POSTMORTEM_ROLES = {"admin", "sre"}
_VIEWER_ROLES = {"viewer", "operator", "sre", "admin"}


class ChronicleService:
    """Provides ChronicleService behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, *, log_path: str = _dat("chronicle.log")) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        settings = get_settings()
        self._log_path = Path(log_path)
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._incidents: Dict[str, ChronicleIncident] = {}
        self._timeline: Dict[str, List[ChronicleTimelineEntry]] = defaultdict(list)
        self._annotations: Dict[str, List[ChronicleAnnotation]] = defaultdict(list)
        self._postmortems: Dict[str, ChroniclePostmortem] = {}
        self._default_environment = settings.environment
        self._default_region = settings.region

    def _incident_key(self, service: str, environment: str, region: str) -> str:
        """Builds incident key using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        return f"inc-{service}-{environment}-{region}".replace(" ", "-").lower()

    def _append_log(self, payload: Dict[str, object]) -> None:
        """Builds append log using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        try:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=True) + "\n")
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to write Chronicle log entry", extra={"error": str(exc)})

    def _ensure_incident(
        self,
        *,
        service: str,
        environment: Optional[str],
        region: Optional[str],
        summary: str,
        severity: str,
        tags: Optional[List[str]] = None,
    ) -> ChronicleIncident:
        """Ensures incident using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        resolved_environment = environment or self._default_environment
        resolved_region = region or self._default_region
        incident_id = self._incident_key(service, resolved_environment, resolved_region)
        incident = self._incidents.get(incident_id)
        if incident is None:
            incident = ChronicleIncident(
                incident_id=incident_id,
                service=service,
                environment=resolved_environment,
                region=resolved_region,
                summary=summary,
                severity=severity,
                tags=list(tags or []),
            )
            self._incidents[incident_id] = incident
            self._correlate_deploys(incident)
            self._surface_blast_radius(incident)
        else:
            incident.updated_at = datetime.utcnow()
            incident.severity = severity if severity else incident.severity
            if summary:
                incident.summary = summary
            for tag in tags or []:
                if tag not in incident.tags:
                    incident.tags.append(tag)
        return incident

    def _surface_blast_radius(self, incident: ChronicleIncident) -> None:
        """On new incident: surface which services may be affected via the dependency graph."""
        try:
            from ..services.tracing.graph import surface_blast_radius
            summary = surface_blast_radius(incident.service, incident.incident_id)
            if not summary:
                return
            entry = create_timeline_entry(
                incident.incident_id,
                component="graph",
                event_type="dependency.blast_radius",
                summary=f"Blast radius analysis for {incident.service}:\n{summary}",
                severity="info",
                correlation_ids={},
            )
            self._timeline[incident.incident_id].append(entry)
            self._append_log({"kind": "timeline", **chronicle_to_dict(entry)})
            logger.info("Blast radius surfaced for incident %s (%s)", incident.incident_id, incident.service)
        except Exception as exc:
            logger.debug("Blast radius surface failed (non-critical): %s", exc)

    def _correlate_deploys(self, incident: ChronicleIncident) -> None:
        """On new incident: query for recent GitHub deployments to the same service
        and add a timeline entry if any are found in the last 30 minutes."""
        try:
            from ..db.base import SessionLocal
            from ..api.routers.github import find_preceding_deploys
            with SessionLocal() as db:
                deploys = find_preceding_deploys(
                    db, incident.service, incident.started_at, lookback_minutes=30
                )
            if not deploys:
                return
            lines = []
            for d in deploys:
                lines.append(
                    f"  {d['repo']}@{d['sha']} ({d['ref']}) by {d.get('deployer') or 'unknown'}"
                    f" — {d['minutes_before_incident']:.0f}m before incident"
                )
            summary = (
                f"{len(deploys)} deployment(s) preceded this incident:\n" + "\n".join(lines)
            )
            entry = create_timeline_entry(
                incident.incident_id,
                component="github",
                event_type="deploy.correlation",
                summary=summary,
                severity="info",
                correlation_ids={},
            )
            self._timeline[incident.incident_id].append(entry)
            self._append_log({"kind": "timeline", **chronicle_to_dict(entry)})
            logger.info(
                "Deploy correlation: %d deploy(s) found for %s within 30m of incident",
                len(deploys), incident.service,
            )
        except Exception as exc:
            logger.debug("Deploy correlation failed (non-critical): %s", exc)

    def ingest_component_event(
        self,
        *,
        component: str,
        event_type: str,
        summary: str,
        metadata: Optional[Dict[str, object]] = None,
        correlation_ids: Optional[Dict[str, str]] = None,
        signal_id: Optional[str] = None,
        severity: str = "info",
        tags: Optional[List[str]] = None,
    ) -> ChronicleTimelineEntry:
        """Ingests component event using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        data = metadata or {}
        service = str(data.get("service", "unknown"))
        environment = data.get("environment")
        region = data.get("region")
        decision_id = data.get("decision_id")
        action_id = data.get("action_id")
        near_miss = bool(data.get("near_miss", False)) or event_type.startswith("verification.")
        if isinstance(data.get("status"), str) and str(data.get("status")) in {"fail", "timeout", "escalate"}:
            near_miss = True

        incident = self._ensure_incident(
            service=service,
            environment=str(environment) if environment else None,
            region=str(region) if region else None,
            summary=summary,
            severity=severity,
            tags=tags,
        )

        entry = create_timeline_entry(
            incident.incident_id,
            component=component,
            event_type=event_type,
            summary=summary,
            severity=severity,
            signal_id=signal_id,
            decision_id=str(decision_id) if decision_id else None,
            action_id=str(action_id) if action_id else None,
            correlation_ids={k: str(v) for k, v in (correlation_ids or {}).items()},
            metadata=data,
            tags=tags or [],
            near_miss=near_miss,
        )
        self._timeline[incident.incident_id].append(entry)
        if entry.decision_id and entry.decision_id not in incident.decision_ids:
            incident.decision_ids.append(entry.decision_id)
        incident.updated_at = datetime.utcnow()
        self._append_log({"kind": "timeline", **chronicle_to_dict(entry)})
        return entry

    def list_incidents(
        self,
        *,
        limit: int = 100,
        service: Optional[str] = None,
        severity: Optional[str] = None,
        region: Optional[str] = None,
        started_after: Optional[datetime] = None,
        ended_before: Optional[datetime] = None,
        actor_role: str = "viewer",
    ) -> List[ChronicleIncident]:
        """Lists incidents using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        if actor_role not in _VIEWER_ROLES:
            raise PermissionError(f"role {actor_role} cannot view incidents")
        incidents = sorted(
            self._incidents.values(),
            key=lambda item: item.updated_at,
            reverse=True,
        )
        filtered: List[ChronicleIncident] = []
        for incident in incidents:
            if service and incident.service != service:
                continue
            if severity and incident.severity != severity:
                continue
            if region and incident.region != region:
                continue
            if started_after and incident.started_at < started_after:
                continue
            if ended_before and incident.updated_at > ended_before:
                continue
            filtered.append(incident)
        return filtered[:limit]

    def get_incident(self, incident_id: str) -> Optional[ChronicleIncident]:
        """Gets incident using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        return self._incidents.get(incident_id)

    def list_timeline(
        self,
        incident_id: str,
        *,
        limit: int = 500,
        actor_role: str = "viewer",
        severity: Optional[str] = None,
        event_type: Optional[str] = None,
        started_after: Optional[datetime] = None,
        ended_before: Optional[datetime] = None,
    ) -> List[ChronicleTimelineEntry]:
        """Lists timeline using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        if actor_role not in _VIEWER_ROLES:
            raise PermissionError(f"role {actor_role} cannot view timelines")
        events = self._timeline.get(incident_id, [])
        filtered: List[ChronicleTimelineEntry] = []
        for event in events:
            if severity and event.severity != severity:
                continue
            if event_type and event.event_type != event_type:
                continue
            if started_after and event.happened_at < started_after:
                continue
            if ended_before and event.happened_at > ended_before:
                continue
            filtered.append(event)
        return filtered[-limit:]

    def add_annotation(
        self,
        incident_id: str,
        *,
        author: str,
        note: str,
        actor_role: str = "operator",
        tags: Optional[List[str]] = None,
        attachments: Optional[List[str]] = None,
    ) -> ChronicleAnnotation:
        """Builds add annotation using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if actor_role not in _ANNOTATION_ROLES:
            raise PermissionError(f"role {actor_role} cannot annotate incidents")
        if incident_id not in self._incidents:
            raise KeyError(f"incident {incident_id} not found")
        annotation = create_annotation(
            incident_id,
            author=author,
            note=note,
            tags=tags,
            attachments=attachments,
        )
        self._annotations[incident_id].append(annotation)
        self._append_log({"kind": "annotation", **chronicle_to_dict(annotation)})
        return annotation

    def list_annotations(self, incident_id: str, *, limit: int = 100) -> List[ChronicleAnnotation]:
        """Lists annotations using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        items = self._annotations.get(incident_id, [])
        return items[-limit:]

    def upsert_postmortem(
        self,
        incident_id: str,
        *,
        actor_role: str = "sre",
        template_version: str = "v1",
        summary: Optional[str] = None,
        impact: Optional[str] = None,
        root_cause: Optional[str] = None,
        timeline_summary: Optional[str] = None,
        lessons_learned: Optional[List[str]] = None,
        follow_up_actions: Optional[List[str]] = None,
    ) -> ChroniclePostmortem:
        """Upserts postmortem using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if actor_role not in _POSTMORTEM_ROLES:
            raise PermissionError(f"role {actor_role} cannot edit postmortems")
        if incident_id not in self._incidents:
            raise KeyError(f"incident {incident_id} not found")
        current = self._postmortems.get(incident_id) or create_postmortem(
            incident_id,
            template_version=template_version,
        )
        if summary is not None:
            current.summary = summary
        if impact is not None:
            current.impact = impact
        if root_cause is not None:
            current.root_cause = root_cause
        if timeline_summary is not None:
            current.timeline_summary = timeline_summary
        if lessons_learned is not None:
            current.lessons_learned = lessons_learned
        if follow_up_actions is not None:
            current.follow_up_actions = follow_up_actions
        current.updated_at = datetime.utcnow()
        self._postmortems[incident_id] = current
        self._append_log({"kind": "postmortem", **chronicle_to_dict(current)})
        return current

    def get_postmortem(self, incident_id: str) -> Optional[ChroniclePostmortem]:
        """Gets postmortem using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        return self._postmortems.get(incident_id)

    def link_incidents(self, incident_id: str, linked_incident_id: str) -> ChronicleIncident:
        """Builds link incidents using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        incident = self._incidents.get(incident_id)
        other = self._incidents.get(linked_incident_id)
        if incident is None or other is None:
            raise KeyError("both incidents must exist before linking")
        if linked_incident_id not in incident.linked_incidents:
            incident.linked_incidents.append(linked_incident_id)
        if incident_id not in other.linked_incidents:
            other.linked_incidents.append(incident_id)
        incident.updated_at = datetime.utcnow()
        other.updated_at = datetime.utcnow()
        self._append_log(
            {
                "kind": "incident_link",
                "incident_id": incident_id,
                "linked_incident_id": linked_incident_id,
                "happened_at": datetime.utcnow().isoformat(),
            }
        )
        return incident

    def create_report(self, incident_id: str) -> ChronicleReport:
        """Creates report using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if incident_id not in self._incidents:
            raise KeyError(f"incident {incident_id} not found")
        events = self._timeline.get(incident_id, [])
        report = create_report(incident_id)
        report.entries = list(events)
        report.near_miss_count = sum(1 for event in events if event.near_miss)
        actionable = [event for event in events if event.event_type.startswith("actions.")]
        failed = [
            event
            for event in actionable
            if str(event.metadata.get("status", "")).lower() in {"failed", "fail"}
        ]
        report.action_failure_rate = (len(failed) / len(actionable)) if actionable else 0.0
        tag_set = set()
        for event in events:
            tag_set.update(event.tags)
        report.tags = sorted(tag_set)
        return report

    def report_summary(self) -> Dict[str, object]:
        """Builds report summary using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        incidents = self.list_incidents(limit=1000)
        open_count = sum(1 for item in incidents if item.status == "open")
        near_miss_total = 0
        for incident in incidents:
            near_miss_total += sum(1 for item in self._timeline.get(incident.incident_id, []) if item.near_miss)
        return {
            "incidents_total": len(incidents),
            "incidents_open": open_count,
            "incidents_resolved": len(incidents) - open_count,
            "near_miss_total": near_miss_total,
        }

    def clear(self) -> None:
        """Clears the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._incidents.clear()
        self._timeline.clear()
        self._annotations.clear()
        self._postmortems.clear()
        if self._log_path.exists():
            self._log_path.unlink()


chronicle_service = ChronicleService()