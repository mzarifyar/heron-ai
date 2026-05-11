"""Golden Signals API — the four metrics that matter for every service."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...db.models import Signal, ServiceEdgeMetric, ServiceMetricBaseline
from ...services.golden_signals.collector import golden_signals_collector
from ...services.golden_signals.baseline import baseline_engine

router = APIRouter(prefix="/golden-signals", tags=["golden-signals"])

SERVICES = [
    "api-gateway", "auth-service", "payment-processor",
    "recommendation-engine", "data-pipeline", "notification-service",
    "search-service", "user-profile", "inventory-service", "checkout-service",
]


@router.get("/summary")
def golden_signals_summary(db: Session = Depends(get_db)) -> dict:
    """Health summary for all services — the four signals at a glance."""
    since = datetime.utcnow() - timedelta(minutes=5)

    # Get distinct services from recent signals
    services = db.execute(
        select(Signal.service).where(Signal.timestamp >= since).distinct()
    ).scalars().all()

    if not services:
        # Fall back to known services list when no live data yet
        services = SERVICES

    results = []
    for svc in sorted(services):
        data = golden_signals_collector.get_current_signals(svc)
        # Overall health: worst of the four signals
        severities = [
            data["latency"]["severity"],
            data["traffic"]["severity"],
            data["errors"]["severity"],
            data["saturation"]["cpu_severity"],
            data["saturation"]["memory_severity"],
            data["saturation"]["pool_severity"],
        ]
        rank = {"critical": 3, "warning": 2, "unknown": 1, "ok": 0}
        overall = max(severities, key=lambda s: rank.get(s, 0))
        results.append({
            "service": svc,
            "overall_health": overall,
            "latency_p99_ms": data["latency"]["p99_ms"],
            "error_rate_pct": data["errors"]["rate_pct"],
            "rps": data["traffic"]["rps"],
            "pool_pct": data["saturation"]["connection_pool_pct"],
            "latency_severity": data["latency"]["severity"],
            "error_severity": data["errors"]["severity"],
            "saturation_severity": data["saturation"]["pool_severity"],
        })

    return {"items": results, "count": len(results), "computed_at": datetime.utcnow().isoformat()}


@router.get("/{service}")
def get_service_signals(service: str) -> dict:
    """Full four golden signals for a single service with baseline comparison."""
    return golden_signals_collector.get_current_signals(service)


@router.get("/edges/all")
def get_edge_metrics(
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
) -> dict:
    """RED metrics per service-to-service edge (latest reading per pair)."""
    since = datetime.utcnow() - timedelta(minutes=10)

    rows = db.execute(
        select(ServiceEdgeMetric)
        .where(
            ServiceEdgeMetric.timestamp >= since,
            ServiceEdgeMetric.source_service != ServiceEdgeMetric.dest_service,
        )
        .order_by(ServiceEdgeMetric.timestamp.desc())
        .limit(limit)
    ).scalars().all()

    return {
        "items": [
            {
                "source": r.source_service,
                "dest": r.dest_service,
                "cluster": r.cluster,
                "p50_ms": r.p50_ms,
                "p95_ms": r.p95_ms,
                "p99_ms": r.p99_ms,
                "rps": r.rps,
                "error_rate_pct": round(r.error_rate * 100, 3),
                "timestamp": r.timestamp.isoformat(),
                "health": (
                    "critical" if r.error_rate > 0.05 or r.p99_ms > 2000 else
                    "warning"  if r.error_rate > 0.01 or r.p99_ms > 500 else
                    "ok"
                ),
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/baselines/all")
def get_baselines(
    service: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Current baselines — what Heron considers 'normal' for each service."""
    q = select(ServiceMetricBaseline)
    if service:
        q = q.where(ServiceMetricBaseline.service == service)
    q = q.order_by(ServiceMetricBaseline.service, ServiceMetricBaseline.metric_name)

    rows = db.execute(q).scalars().all()
    return {
        "items": [
            {
                "service": r.service,
                "metric": r.metric_name,
                "hour": r.hour_of_day,
                "mean": round(r.mean, 4),
                "p95": round(r.p95, 4),
                "p99": round(r.p99, 4),
                "samples": r.sample_count,
                "computed_at": r.computed_at.isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.post("/baselines/recompute")
def recompute_baselines() -> dict:
    """Trigger an immediate baseline recomputation."""
    written = baseline_engine.compute_all()
    return {"baselines_written": written, "computed_at": datetime.utcnow().isoformat()}
