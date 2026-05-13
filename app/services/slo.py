"""SLO / Error Budget tracking service.

Manages SLO definitions and computes error budget burn rate from Signal data.

Error budget = (1 - SLO target) * window_seconds
  e.g. 99.9% SLO over 30 days = 0.1% * 2,592,000s = 2,592s of allowed downtime

Burn rate = current_error_rate / allowed_error_rate
  e.g. error_rate=0.5% against 0.1% SLO = 5× burn rate
  At 5× burn rate the monthly budget is consumed in 6 days.

Budget remaining = 1 - (errors_observed / total_error_budget)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from ..core import get_logger

logger = get_logger(__name__)


# ── CRUD helpers ──────────────────────────────────────────────────────────────

def create_slo(
    db: Any,
    *,
    service: str,
    name: str,
    metric_name: str,
    target: float,
    window_days: int = 30,
    alert_threshold: float = 0.10,
    description: str = "",
) -> dict[str, Any]:
    """Create a new SLO definition."""
    from ..db.models import ServiceSLO
    slo = ServiceSLO(
        id=str(uuid.uuid4()),
        service=service,
        name=name,
        metric_name=metric_name,
        target=round(target, 6),
        window_days=window_days,
        alert_threshold=round(alert_threshold, 4),
        description=description,
        enabled=True,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(slo)
    db.commit()
    return _slo_to_dict(slo)


def list_slos(db: Any, service: str | None = None) -> list[dict[str, Any]]:
    from ..db.models import ServiceSLO
    from sqlalchemy import select
    q = select(ServiceSLO).where(ServiceSLO.enabled.is_(True))
    if service:
        q = q.where(ServiceSLO.service == service)
    return [_slo_to_dict(r) for r in db.execute(q).scalars().all()]


def delete_slo(db: Any, slo_id: str) -> bool:
    from ..db.models import ServiceSLO
    slo = db.get(ServiceSLO, slo_id)
    if not slo:
        return False
    slo.enabled = False
    db.commit()
    return True


# ── Burn rate computation ─────────────────────────────────────────────────────

def compute_burn(db: Any, slo_id: str) -> dict[str, Any] | None:
    """Compute current error budget status for an SLO.

    Reads Signal table for the metric over the SLO window and calculates
    observed error rate, budget consumed, and burn rate.
    """
    from ..db.models import ServiceSLO, Signal, SLOBurnEvent
    from sqlalchemy import select, func

    slo = db.get(ServiceSLO, slo_id)
    if not slo or not slo.enabled:
        return None

    since = datetime.utcnow() - timedelta(days=slo.window_days)

    # Average observed metric value over the window
    row = db.execute(
        select(func.avg(Signal.value).label("avg_val"), func.count().label("n"))
        .where(
            Signal.service == slo.service,
            Signal.metric_name == slo.metric_name,
            Signal.timestamp >= since,
        )
    ).one()

    observed = float(row.avg_val or 0.0)
    n_samples = int(row.n or 0)

    allowed_error_rate = 1.0 - slo.target           # e.g. 0.001 for 99.9%
    total_budget_seconds = allowed_error_rate * slo.window_days * 86400

    # Fraction of budget consumed
    if allowed_error_rate > 0:
        budget_consumed = min(1.0, observed / allowed_error_rate)
        burn_rate = observed / allowed_error_rate if allowed_error_rate > 0 else 0.0
    else:
        budget_consumed = 1.0
        burn_rate = 0.0

    budget_remaining = max(0.0, 1.0 - budget_consumed)
    alert = budget_remaining <= slo.alert_threshold

    # Record burn event
    event = SLOBurnEvent(
        id=str(uuid.uuid4()),
        slo_id=slo_id,
        service=slo.service,
        error_rate=round(observed, 6),
        budget_remaining=round(budget_remaining, 4),
        burn_rate=round(burn_rate, 3),
        recorded_at=datetime.utcnow(),
        alert_fired=alert,
    )
    db.add(event)
    db.commit()

    result = {
        "slo_id": slo_id,
        "service": slo.service,
        "name": slo.name,
        "metric_name": slo.metric_name,
        "target": slo.target,
        "window_days": slo.window_days,
        "observed_error_rate": round(observed, 6),
        "allowed_error_rate": round(allowed_error_rate, 6),
        "budget_remaining_pct": round(budget_remaining * 100, 2),
        "burn_rate": round(burn_rate, 3),
        "alert": alert,
        "n_samples": n_samples,
        "status": _status(budget_remaining, burn_rate),
        "budget_seconds_total": round(total_budget_seconds, 0),
        "budget_seconds_remaining": round(total_budget_seconds * budget_remaining, 0),
    }

    if alert:
        logger.warning(
            "SLO alert: %s/%s budget_remaining=%.1f%% burn_rate=%.1fx",
            slo.service, slo.name, budget_remaining * 100, burn_rate,
        )

    return result


def compute_all_burns(db: Any) -> list[dict[str, Any]]:
    """Compute burn rate for all enabled SLOs."""
    from ..db.models import ServiceSLO
    from sqlalchemy import select
    slos = db.execute(select(ServiceSLO).where(ServiceSLO.enabled.is_(True))).scalars().all()
    results = []
    for slo in slos:
        r = compute_burn(db, slo.id)
        if r:
            results.append(r)
    return results


def get_burn_history(db: Any, slo_id: str, limit: int = 30) -> list[dict[str, Any]]:
    from ..db.models import SLOBurnEvent
    from sqlalchemy import select
    rows = db.execute(
        select(SLOBurnEvent)
        .where(SLOBurnEvent.slo_id == slo_id)
        .order_by(SLOBurnEvent.recorded_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        {
            "recorded_at": r.recorded_at.isoformat(),
            "error_rate": r.error_rate,
            "budget_remaining_pct": round(r.budget_remaining * 100, 2),
            "burn_rate": r.burn_rate,
            "alert_fired": r.alert_fired,
        }
        for r in rows
    ]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _status(budget_remaining: float, burn_rate: float) -> str:
    if budget_remaining <= 0.02:
        return "exhausted"
    if budget_remaining <= 0.10 or burn_rate >= 5:
        return "critical"
    if budget_remaining <= 0.25 or burn_rate >= 2:
        return "warning"
    return "healthy"


def _slo_to_dict(slo: Any) -> dict[str, Any]:
    return {
        "id": slo.id,
        "service": slo.service,
        "name": slo.name,
        "metric_name": slo.metric_name,
        "target": slo.target,
        "target_pct": round(slo.target * 100, 4),
        "window_days": slo.window_days,
        "alert_threshold": slo.alert_threshold,
        "description": slo.description or "",
        "enabled": slo.enabled,
        "created_at": slo.created_at.isoformat(),
    }


def seed_default_slos(db: Any) -> int:
    """Seed sensible default SLOs for the known demo services if none exist."""
    from ..db.models import ServiceSLO
    from sqlalchemy import select
    existing = db.execute(select(ServiceSLO.service)).scalars().all()
    if existing:
        return 0

    defaults = [
        ("api-gateway",          "API Gateway Availability",      "error_rate", 0.999,  30),
        ("checkout-service",     "Checkout Success Rate",          "error_rate", 0.999,  30),
        ("payment-processor",    "Payment Success Rate",           "error_rate", 0.9995, 30),
        ("auth-service",         "Auth Service Availability",      "error_rate", 0.9999, 30),
        ("search-service",       "Search Availability",            "error_rate", 0.99,   30),
        ("recommendation-engine","Recommendation Availability",    "error_rate", 0.99,   30),
        ("notification-service", "Notification Delivery Rate",     "error_rate", 0.995,  30),
        ("data-pipeline",        "Pipeline Throughput SLO",        "error_rate", 0.99,   30),
    ]

    count = 0
    for svc, name, metric, target, window in defaults:
        create_slo(db, service=svc, name=name, metric_name=metric,
                   target=target, window_days=window)
        count += 1
    return count
