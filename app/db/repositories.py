"""Repository helpers — thin read-only query layer for dashboard endpoints."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .models import (
    Action, ClusterInventory, Incident, Integration,
    LearnOutcome, NearMiss, PullerRun, Recommendation,
    Signal, TimelineEvent,
)


# ── Dashboard Summary ──────────────────────────────────────────────────────

def get_dashboard_summary(db: Session) -> dict[str, Any]:
    now = datetime.utcnow()
    week_start = now - timedelta(days=7)
    prev_week_start = now - timedelta(days=14)

    active = db.scalar(select(func.count()).where(Incident.status == "active")) or 0
    active_by_sev: dict[str, int] = {}
    for sev in ("sev1", "sev2", "sev3", "sev4"):
        c = db.scalar(
            select(func.count()).where(Incident.status == "active", Incident.severity == sev)
        ) or 0
        if c:
            active_by_sev[sev] = c

    # MTTR: resolved incidents last 7 days
    recent_resolved = db.execute(
        select(Incident.mttr_seconds)
        .where(Incident.status == "resolved", Incident.started_at >= week_start, Incident.mttr_seconds.isnot(None))
    ).scalars().all()
    mttr_7 = int(sum(recent_resolved) / len(recent_resolved)) if recent_resolved else None

    prev_resolved = db.execute(
        select(Incident.mttr_seconds).where(
            Incident.status == "resolved",
            Incident.started_at >= prev_week_start,
            Incident.started_at < week_start,
            Incident.mttr_seconds.isnot(None),
        )
    ).scalars().all()
    mttr_prev = int(sum(prev_resolved) / len(prev_resolved)) if prev_resolved else None

    # Auto-heal rate last 30 days
    thirty_ago = now - timedelta(days=30)
    total_30 = db.scalar(
        select(func.count()).where(Incident.started_at >= thirty_ago, Incident.status != "active")
    ) or 0
    healed_30 = db.scalar(
        select(func.count()).where(
            Incident.started_at >= thirty_ago, Incident.auto_healed.is_(True)
        )
    ) or 0
    auto_heal_rate = round(healed_30 / total_30, 3) if total_30 else 0.0

    # This-week total
    this_week = db.scalar(select(func.count()).where(Incident.started_at >= week_start)) or 0

    return {
        "active_incidents": active,
        "active_by_severity": active_by_sev,
        "mttr_last_7_days": mttr_7,
        "mttr_previous_7_days": mttr_prev,
        "auto_heal_rate": auto_heal_rate,
        "total_incidents_this_week": this_week,
        "total_incidents_all_time": db.scalar(select(func.count(Incident.id))) or 0,
    }


def get_alert_volume(db: Session, days: int = 14) -> list[dict[str, Any]]:
    since = datetime.utcnow() - timedelta(days=days)
    rows = db.execute(
        select(
            func.date(Signal.timestamp).label("day"),
            func.count().label("count"),
        )
        .where(Signal.timestamp >= since)
        .group_by(func.date(Signal.timestamp))
        .order_by(func.date(Signal.timestamp))
    ).all()
    return [{"day": str(r.day), "count": r.count} for r in rows]


def get_recent_incidents(db: Session, limit: int = 5) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Incident).order_by(Incident.started_at.desc()).limit(limit)
    ).scalars().all()
    return [_incident_to_dict(r) for r in rows]


def get_integration_status(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(select(Integration).order_by(Integration.name)).scalars().all()
    return [
        {
            "id": r.id,
            "name": r.name,
            "type": r.type,
            "status": r.status,
            "last_synced_at": r.last_synced_at.isoformat() if r.last_synced_at else None,
        }
        for r in rows
    ]


def get_cluster_health(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(select(ClusterInventory).order_by(ClusterInventory.cluster_name)).scalars().all()
    return [
        {
            "id": r.id,
            "cluster_name": r.cluster_name,
            "region": r.region,
            "environment": r.environment,
            "status": r.status,
            "node_count": r.node_count,
            "pod_count": r.pod_count,
            "unhealthy_pods": r.unhealthy_pods or [],
            "last_checked_at": r.last_checked_at.isoformat(),
        }
        for r in rows
    ]


# ── Incidents ──────────────────────────────────────────────────────────────

def list_incidents(
    db: Session,
    *,
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    severity: str | None = None,
    service: str | None = None,
    org_id: str = "default",
) -> tuple[list[dict], int]:
    q = select(Incident).where(Incident.org_id == org_id)
    if status:
        q = q.where(Incident.status == status)
    if severity:
        q = q.where(Incident.severity == severity)
    if service:
        q = q.where(Incident.service == service)
    q = q.order_by(Incident.started_at.desc())
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.execute(q.offset(offset).limit(limit)).scalars().all()
    return [_incident_to_dict(r) for r in rows], total


def get_incident_detail(db: Session, incident_id: str) -> dict[str, Any] | None:
    inc = db.get(Incident, incident_id)
    if not inc:
        return None
    timeline = (
        db.execute(
            select(TimelineEvent)
            .where(TimelineEvent.incident_id == incident_id)
            .order_by(TimelineEvent.timestamp)
        )
        .scalars()
        .all()
    )
    return {
        "incident": _incident_to_dict(inc),
        "timeline": [_event_to_dict(e) for e in timeline],
        "annotations": [
            {"id": a.id, "author": a.author, "content": a.content, "created_at": a.created_at.isoformat()}
            for a in inc.annotations
        ],
        "postmortem": (
            {"id": inc.postmortem.id, "content": inc.postmortem.content, "author": inc.postmortem.author,
             "created_at": inc.postmortem.created_at.isoformat()}
            if inc.postmortem else None
        ),
        "actions": [
            {"id": a.id, "action_type": a.action_type, "status": a.status,
             "target": a.target, "executed_at": a.executed_at.isoformat(), "result": a.result}
            for a in inc.actions
        ],
    }


# ── Intelligence ───────────────────────────────────────────────────────────

def get_learn_summary(db: Session) -> dict[str, Any]:
    total = db.scalar(select(func.count(LearnOutcome.id))) or 0
    success = db.scalar(
        select(func.count()).where(LearnOutcome.outcome == "success")
    ) or 0
    rate = round(success / total, 3) if total else 0.0

    rows = db.execute(
        select(
            LearnOutcome.action_type,
            LearnOutcome.service,
            func.count().label("cnt"),
            func.sum(
                case((LearnOutcome.outcome == "success", 1), else_=0)
            ).label("wins"),
        )
        .group_by(LearnOutcome.action_type, LearnOutcome.service)
        .order_by(func.count().desc())
        .limit(10)
    ).all()

    top_actions = [
        {
            "action": r.action_type,
            "service": r.service,
            "count": r.cnt,
            "success_rate": round(r.wins / r.cnt, 2) if r.cnt else 0,
        }
        for r in rows
    ]

    recent = db.execute(
        select(LearnOutcome).order_by(LearnOutcome.recorded_at.desc()).limit(8)
    ).scalars().all()

    return {
        "total_outcomes": total,
        "success_rate": rate,
        "top_actions": top_actions,
        "recent_outcomes": [
            {"action": o.action_type, "service": o.service, "result": o.outcome,
             "recorded_at": o.recorded_at.isoformat()}
            for o in recent
        ],
    }


def get_recommendations(db: Session) -> list[dict[str, Any]]:
    rows = db.execute(
        select(Recommendation)
        .where(Recommendation.status == "pending")
        .order_by(Recommendation.confidence.desc())
        .limit(10)
    ).scalars().all()
    return [
        {"id": r.id, "service": r.service, "action": r.action_type,
         "confidence": r.confidence, "rationale": r.rationale, "status": r.status}
        for r in rows
    ]


def get_near_misses(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    rows = db.execute(
        select(NearMiss).order_by(NearMiss.detected_at.desc()).limit(limit)
    ).scalars().all()
    return [
        {"id": r.id, "service": r.service, "region": r.region, "metric_name": r.metric_name,
         "peak_value": r.peak_value, "threshold": r.threshold, "gap_percent": r.gap_percent,
         "detected_at": r.detected_at.isoformat()}
        for r in rows
    ]


# ── Private helpers ────────────────────────────────────────────────────────

def _incident_to_dict(inc: Incident) -> dict[str, Any]:
    return {
        "id": inc.id,
        "title": inc.title,
        "severity": inc.severity,
        "status": inc.status,
        "service": inc.service,
        "region": inc.region,
        "environment": inc.environment,
        "auto_healed": inc.auto_healed,
        "mttr_seconds": inc.mttr_seconds,
        "duration_seconds": inc.duration_seconds,
        "started_at": inc.started_at.isoformat(),
        "resolved_at": inc.resolved_at.isoformat() if inc.resolved_at else None,
        "created_at": inc.created_at.isoformat(),
    }


def _event_to_dict(e: TimelineEvent) -> dict[str, Any]:
    return {
        "id": e.id,
        "incident_id": e.incident_id,
        "event_type": e.event_type,
        "description": e.description,
        "actor": e.actor,
        "severity": e.severity,
        "timestamp": e.timestamp.isoformat(),
        "metadata": e.metadata_,
    }
