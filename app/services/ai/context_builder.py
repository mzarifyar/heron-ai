"""Context builder — assembles incident history and signal data for the LLM prompt."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select

from ...db.base import SessionLocal
from ...db.models import Signal
from ...core.paths import config as _cfg
from ...core import get_logger

logger = get_logger(__name__)


def build_context(
    *,
    service: str,
    severity: str,
    region: str,
    environment: str,
    metric_name: str,
    observed_value: float,
    threshold: float,
    signal_summary: str,
    learn_scores: dict[str, Any],
) -> dict[str, Any]:
    """Gather all context needed for the LLM decision prompt."""
    return {
        "incident": {
            "service": service,
            "severity": severity,
            "region": region,
            "environment": environment,
            "metric_name": metric_name,
            "observed_value": observed_value,
            "threshold": threshold,
            "summary": signal_summary,
        },
        "recent_signals": _recent_signals(service),
        "chronicle_history": _chronicle_history(service),
        "learn_scores": _format_learn_scores(learn_scores),
        "policy_summary": _policy_summary(),
        "available_actions": _available_actions(),
        "service_dependencies": _service_dependencies(service),
    }


def _recent_signals(service: str) -> list[dict]:
    """Last 30 minutes of signals for this service."""
    since = datetime.utcnow() - timedelta(minutes=30)
    try:
        with SessionLocal() as db:
            rows = db.execute(
                select(Signal.metric_name, Signal.value, Signal.severity, Signal.timestamp)
                .where(Signal.service == service, Signal.timestamp >= since)
                .order_by(Signal.timestamp.desc())
                .limit(20)
            ).all()
        return [
            {
                "metric": r.metric_name,
                "value": round(r.value, 4),
                "severity": r.severity,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.debug("Context: recent signals query failed: %s", exc)
        return []


def _chronicle_history(service: str) -> list[dict]:
    """Last 5 incidents for this service from the incidents DB table."""
    try:
        from ...db.models import Incident as DBIncident, TimelineEvent
        since = datetime.utcnow() - timedelta(days=90)
        with SessionLocal() as db:
            incidents = db.execute(
                select(DBIncident)
                .where(DBIncident.service == service, DBIncident.started_at >= since)
                .order_by(DBIncident.started_at.desc())
                .limit(5)
            ).scalars().all()

            history = []
            for inc in incidents:
                # Get last 3 timeline events
                events = db.execute(
                    select(TimelineEvent.event_type, TimelineEvent.description)
                    .where(TimelineEvent.incident_id == inc.id)
                    .order_by(TimelineEvent.timestamp)
                    .limit(3)
                ).all()
                history.append({
                    "incident_id": inc.id,
                    "title": inc.title,
                    "severity": inc.severity,
                    "status": inc.status,
                    "auto_healed": inc.auto_healed,
                    "mttr_seconds": inc.mttr_seconds,
                    "started_at": inc.started_at.isoformat(),
                    "key_events": [
                        {"type": e.event_type, "desc": e.description[:120]}
                        for e in events
                    ],
                })
        return history
    except Exception as exc:
        logger.debug("Context: chronicle history query failed: %s", exc)
        return []


def _format_learn_scores(scores: dict[str, Any]) -> list[dict]:
    """Format learn service scores into prompt-friendly list."""
    scoped = scores.get("scoped", [])
    if not scoped:
        return scores.get("global", [])[:8]
    return sorted(
        scoped[:8],
        key=lambda x: x.get("success_rate", 0),
        reverse=True,
    )


def _policy_summary() -> str:
    """Load policy.yaml and extract a brief summary for the prompt."""
    try:
        import yaml
        path = Path(_cfg("policy.yaml"))
        if not path.exists():
            return "No policy file found — all actions permitted."
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        # Extract high-level rules as a short summary
        rules = data.get("rules", [])
        if not rules:
            return "Policy loaded but no rules defined."
        lines = []
        for rule in rules[:5]:
            name = rule.get("name", "unnamed")
            action = rule.get("action", "unknown")
            lines.append(f"- Rule '{name}': {action}")
        return "\n".join(lines)
    except Exception as exc:
        logger.debug("Context: policy load failed: %s", exc)
        return "Policy unavailable."


def _available_actions() -> list[str]:
    """Load the list of registered action names from actions.yaml."""
    try:
        import yaml
        path = Path(_cfg("actions.yaml"))
        if not path.exists():
            return ["restart_component", "rollback_latest_deployment",
                    "escalate_incident", "page_on_call", "observe_only"]
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        actions = data.get("actions", [])
        if isinstance(actions, list):
            return [a.get("name", str(a)) if isinstance(a, dict) else str(a)
                    for a in actions[:15]]
        return ["restart_component", "rollback_latest_deployment", "escalate_incident",
                "page_on_call", "observe_only"]
    except Exception as exc:
        logger.debug("Context: actions load failed: %s", exc)
        return ["restart_component", "rollback_latest_deployment",
                "escalate_incident", "page_on_call", "observe_only"]


def _service_dependencies(service: str) -> dict[str, Any]:
    """Return upstream/downstream services from the live dependency graph."""
    try:
        from ..tracing.graph import get_graph
        g = get_graph()
        upstream   = list(g.upstream(service, max_depth=3).keys())
        downstream = list(g.downstream(service, max_depth=3).keys())
        blast      = g.blast_radius(service)["affected_services"]
        return {
            "upstream":   upstream[:10],
            "downstream": downstream[:10],
            "blast_radius": blast[:10],
        }
    except Exception as exc:
        logger.debug("Context: dependency graph unavailable: %s", exc)
        return {"upstream": [], "downstream": [], "blast_radius": []}
