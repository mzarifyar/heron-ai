"""Dashboard aggregate endpoints — powers the React Dashboard page."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...db import repositories as repo

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
def dashboard_summary(db: Session = Depends(get_db)) -> dict:
    """Active incidents, MTTR trend, auto-heal rate, weekly totals."""
    return repo.get_dashboard_summary(db)


@router.get("/alert-volume")
def alert_volume(days: int = 14, db: Session = Depends(get_db)) -> dict:
    """Signal counts per calendar day for the last N days (trend chart)."""
    items = repo.get_alert_volume(db, days=days)
    return {"days": days, "items": items}


@router.get("/recent-incidents")
def recent_incidents(limit: int = 5, db: Session = Depends(get_db)) -> dict:
    """Last N incidents with key fields for the recent-activity feed."""
    items = repo.get_recent_incidents(db, limit=limit)
    return {"items": items, "count": len(items)}


@router.get("/integration-status")
def integration_status(db: Session = Depends(get_db)) -> dict:
    """All integrations with connection status."""
    items = repo.get_integration_status(db)
    return {"items": items, "count": len(items)}


@router.get("/cluster-health")
def cluster_health(db: Session = Depends(get_db)) -> dict:
    """All clusters with health summary."""
    items = repo.get_cluster_health(db)
    return {"items": items, "count": len(items)}


# ── Incidents (DB-backed, replaces in-memory chronicle for new data) ────────

@router.get("/incidents")
def list_db_incidents(
    limit: int = 100,
    offset: int = 0,
    status: str | None = None,
    severity: str | None = None,
    service: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Paginated incident list from the database."""
    items, total = repo.list_incidents(
        db, limit=limit, offset=offset, status=status, severity=severity, service=service
    )
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/incidents/{incident_id}")
def get_db_incident(incident_id: str, db: Session = Depends(get_db)) -> dict:
    """Full incident detail with timeline, annotations, postmortem, and actions."""
    detail = repo.get_incident_detail(db, incident_id)
    if detail is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="incident not found")
    return detail


@router.post("/incidents/{incident_id}/mitigate")
def mitigate_incident(incident_id: str, db: Session = Depends(get_db)) -> dict:
    """Ask the AI to analyse this incident and recommend a mitigation plan.

    Builds full context (recent signals, Chronicle history, Learn scores)
    from the incident record and calls the LLM decision advisor.
    The result is recorded in the explain audit trail and appears in the
    Intelligence → AI Decisions card automatically.
    """
    from fastapi import HTTPException
    from ...db.models import Incident
    from ...services.ai.decision_advisor import decision_advisor
    from ...services.learn import learn_service
    from ...schemas.anomaly import Anomaly, create_anomaly
    from ...schemas.signal import (
        SignalContext, SignalPayload, SignalMetric, BufferedSignal,
    )
    from datetime import datetime, timezone
    import uuid

    # Load the incident
    inc = db.get(Incident, incident_id)
    if inc is None:
        raise HTTPException(status_code=404, detail="incident not found")

    # Build a synthetic BufferedSignal so the advisor can use the same
    # context-building code it uses in the autonomous loop
    context = SignalContext(
        org_id=inc.org_id or "default",
        service=inc.service,
        tier="backend",
        environment=inc.environment,
        region=inc.region,
        component=inc.service,
        labels={"triggered_by": "manual_mitigate", "incident_id": incident_id},
    )
    signal = SignalPayload(
        signal_id=f"manual-{uuid.uuid4().hex[:8]}",
        type="event",
        detected_at=datetime.now(timezone.utc),
        summary=inc.title,
        details={
            "metric_name": "incident_trigger",
            "severity": inc.severity,
            "threshold": 0,
            "observed": 1,
            "incident_id": incident_id,
            "manual_trigger": True,
        },
    )
    buffered = BufferedSignal(context=context, signal=signal)

    # Synthetic anomaly so the advisor receives proper severity context
    anomaly = create_anomaly(
        severity=inc.severity,  # type: ignore[arg-type]
        buffered_signal=buffered,
        threshold=0.0,
        observed_value=1.0,
        rationale=f"Manual mitigation triggered for: {inc.title}",
        confidence=0.9,
    )

    learn_scores = learn_service.recommendations(
        service=inc.service, severity=inc.severity
    )

    result = decision_advisor.advise(
        anomalies=[anomaly],
        buffered_signal=buffered,
        severity=inc.severity,
        learn_scores=learn_scores,
    )

    if result is None:
        return {
            "ok": False,
            "error": "AI provider not configured. Set HERON_AI_PROVIDER and HERON_AI_API_KEY in .env",
            "incident_id": incident_id,
        }

    steps, confidence, reasoning, escalate = result

    return {
        "ok": True,
        "incident_id": incident_id,
        "incident_title": inc.title,
        "service": inc.service,
        "severity": inc.severity,
        "confidence": confidence,
        "escalate_immediately": escalate,
        "escalate_reason": None,
        "reasoning": reasoning,
        "steps": [
            {
                "action": s.action,
                "rationale": s.rationale,
                "priority": s.priority,
                "requires_approval": s.requires_approval,
                "parameters": s.parameters,
            }
            for s in steps
        ],
    }


# ── Intelligence (DB-backed) ────────────────────────────────────────────────

@router.get("/learn-summary")
def learn_summary_db(db: Session = Depends(get_db)) -> dict:
    """Learn loop summary from the database (richer than in-memory)."""
    return repo.get_learn_summary(db)


@router.get("/recommendations")
def recommendations_db(db: Session = Depends(get_db)) -> dict:
    """AI action recommendations ranked by confidence."""
    items = repo.get_recommendations(db)
    return {"items": items, "count": len(items)}


@router.post("/recommendations/generate")
def generate_recommendations(lookback_days: int = 90, db: Session = Depends(get_db)) -> dict:
    """Derive algorithmic recommendations from LearnOutcome history and persist them."""
    items = repo.generate_recommendations(db, lookback_days=lookback_days)
    return {"generated": len(items), "items": items}


@router.post("/intelligence/generate")
def generate_intelligence(lookback_days: int = 30) -> dict:
    """Call the LLM to generate AI insights from Chronicle history.

    Rate-limited to once per hour. Requires HERON_AI_PROVIDER + HERON_AI_API_KEY.
    Results are persisted to the Recommendation table and immediately visible
    on the Intelligence page via GET /recommendations.
    """
    from ...services.ai.insight_generator import generate_insights, seconds_until_next_run
    wait = seconds_until_next_run()
    if wait > 0:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=429,
            detail=f"Rate limited — try again in {wait}s (max once per hour).",
        )
    return generate_insights(lookback_days=lookback_days)


@router.get("/near-misses")
def near_misses_db(limit: int = 20, db: Session = Depends(get_db)) -> dict:
    """Near-miss events from the database."""
    items = repo.get_near_misses(db, limit=limit)
    return {"items": items, "count": len(items)}
