"""Cortex Escalate orchestration service.

"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List

from ..core import get_logger
from ..integrations import jira
from ..integrations.pagerduty import trigger_incident
from ..integrations.slack import send_message
from ..schemas.escalation import EscalationEvent, EscalationRequest, create_escalation
from .explain import explain_service

logger = get_logger(__name__)


class EscalationService:
    """Provides EscalationService behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._events: List[EscalationEvent] = []
        self._dedupe_seen: Dict[str, datetime] = {}

    def _dedupe_key(self, request: EscalationRequest) -> str:
        """Builds dedupe key using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        raw = f"{request.service}|{request.severity}|{request.summary}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _structured_message(self, event: EscalationEvent) -> str:
        """Builds structured message using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        metadata = event.metadata
        actions = metadata.get("actions_taken")
        commands = metadata.get("commands_executed")
        state = metadata.get("current_state")
        runbooks = metadata.get("runbook_links")
        lines: List[str] = [
            f"[{event.severity.upper()}] {event.service}: {event.message}",
            f"Incident Key: {event.incident_key or 'n/a'}",
            f"Decision: {metadata.get('decision_id', 'n/a')}",
        ]
        if actions:
            lines.append(f"Actions Taken: {actions}")
        if commands:
            lines.append(f"Commands Executed: {commands}")
        if state:
            lines.append(f"Current State: {state}")
        if runbooks:
            lines.append(f"Runbooks: {runbooks}")
        return "\n".join(lines)

    def _dispatch(self, event: EscalationEvent, *, dry_run: bool) -> Dict[str, object]:
        """Builds dispatch using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        channel = event.channel.name.lower()
        rendered_message = self._structured_message(event)
        if channel == "slack":
            return send_message(target=event.channel.target, message=rendered_message, dry_run=dry_run)
        if channel == "pagerduty":
            return trigger_incident(target=event.channel.target, message=rendered_message, dry_run=dry_run)
        if channel == "jira":
            if dry_run:
                return {"ok": True, "channel": "jira", "status": "planned", "target": event.channel.target}
            payload = jira.create_issue(
                project_key=event.channel.target,
                summary=rendered_message[:200],
                description=rendered_message,
                issue_type_name="Incident",
            )
            ok = "error" not in payload
            return {"ok": ok, "channel": "jira", "status": "created" if ok else "failed", "response": payload}
        return {"ok": False, "channel": channel, "status": "unsupported"}

    def escalate(self, request: EscalationRequest, *, dry_run: bool = True) -> Dict[str, object]:
        """Builds escalate using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if not request.policy_allows:
            return {"status": "suppressed", "reason": "policy_forbidden", "events": []}
        if request.recovered:
            return {"status": "suppressed", "reason": "recovered", "events": []}

        now = datetime.now(timezone.utc)
        dedupe_key = self._dedupe_key(request)
        seen_at = self._dedupe_seen.get(dedupe_key)
        if seen_at and now - seen_at < timedelta(seconds=request.dedupe_window_seconds):
            return {"status": "deduped", "reason": "recent_duplicate", "events": []}

        events: List[EscalationEvent] = []
        results: List[Dict[str, object]] = []
        incident_key = f"inc-{uuid.uuid4().hex[:8]}"

        for channel in request.channels:
            event = create_escalation(
                channel.name,
                channel.target,
                request.summary,
                severity=request.severity,
                service=request.service,
                incident_key=incident_key,
                metadata={
                    "decision_id": request.decision_id,
                    **request.metadata,
                },
            )
            self._events.append(event)
            events.append(event)
            results.append(self._dispatch(event, dry_run=dry_run))

        self._dedupe_seen[dedupe_key] = now
        explain_service.record_event(
            component="escalate",
            event_type="escalation.dispatched",
            message="Escalation dispatched to configured channels",
            metadata={
                "service": request.service,
                "severity": request.severity,
                "decision_id": request.decision_id,
                "channels": [channel.name for channel in request.channels],
                "dedupe_key": dedupe_key,
                "incident_key": incident_key,
                "results": results,
                "dry_run": dry_run,
            },
        )
        logger.info(
            "Escalation dispatched",
            extra={
                "service": request.service,
                "severity": request.severity,
                "channels": [channel.name for channel in request.channels],
                "incident_key": incident_key,
            },
        )
        return {
            "status": "dispatched",
            "incident_key": incident_key,
            "events": [asdict(event) for event in events],
            "results": results,
        }

    def list_events(self, limit: int = 100) -> List[EscalationEvent]:
        """Lists events using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        return self._events[-limit:]

    def clear(self) -> None:
        """Clears the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._events.clear()
        self._dedupe_seen.clear()


escalate_service = EscalationService()