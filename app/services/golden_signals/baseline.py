"""Dynamic baseline engine — rolling 7-day, time-of-day aware.

Replaces static thresholds in insight.py with baselines computed from
historical signal data. Falls back to static thresholds until enough
data exists (minimum 24 hours of samples).
"""

from __future__ import annotations

import statistics
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ...db.base import SessionLocal
from ...db.models import Signal, ServiceMetricBaseline
from ...core import get_logger

logger = get_logger(__name__)

MIN_SAMPLES = 30          # minimum samples before baseline is trusted
WINDOW_DAYS = 7           # look back this many days
SIGMA_WARN = 2.0          # warn at mean + 2σ
SIGMA_CRITICAL = 3.0      # critical at mean + 3σ


class BaselineEngine:
    """Computes and serves dynamic baselines per service+metric+hour."""

    def compute_all(self) -> int:
        """Recompute baselines for all service+metric combinations.

        Returns the number of baselines written.
        """
        written = 0
        since = datetime.utcnow() - timedelta(days=WINDOW_DAYS)

        with SessionLocal() as db:
            # Get all distinct service+metric pairs
            pairs = db.execute(
                select(Signal.service, Signal.metric_name)
                .where(Signal.timestamp >= since)
                .distinct()
            ).all()

            for service, metric_name in pairs:
                written += self._compute_for_pair(db, service, metric_name, since)
            db.commit()

        logger.info("Baseline computation complete", extra={"baselines_written": written})
        return written

    def _compute_for_pair(
        self, db: Session, service: str, metric_name: str, since: datetime
    ) -> int:
        rows = db.execute(
            select(Signal.value, Signal.timestamp)
            .where(
                Signal.service == service,
                Signal.metric_name == metric_name,
                Signal.timestamp >= since,
            )
            .order_by(Signal.timestamp)
        ).all()

        if len(rows) < MIN_SAMPLES:
            return 0

        # Group by hour-of-day + day-of-week
        buckets: dict[tuple[int, int], list[float]] = {}
        for value, ts in rows:
            key = (ts.hour, ts.weekday())
            buckets.setdefault(key, []).append(value)

        written = 0
        now = datetime.utcnow()

        for (hour, dow), values in buckets.items():
            if len(values) < 3:
                continue

            mean = statistics.mean(values)
            stddev = statistics.pstdev(values) if len(values) > 1 else 0.0
            sorted_vals = sorted(values)
            n = len(sorted_vals)
            p50 = sorted_vals[int(n * 0.50)]
            p95 = sorted_vals[int(n * 0.95)]
            p99 = sorted_vals[min(int(n * 0.99), n - 1)]

            # Upsert: delete existing then insert
            existing = db.execute(
                select(ServiceMetricBaseline).where(
                    ServiceMetricBaseline.service == service,
                    ServiceMetricBaseline.metric_name == metric_name,
                    ServiceMetricBaseline.hour_of_day == hour,
                    ServiceMetricBaseline.day_of_week == dow,
                )
            ).scalar_one_or_none()

            if existing:
                existing.mean = mean
                existing.stddev = stddev
                existing.p50 = p50
                existing.p95 = p95
                existing.p99 = p99
                existing.sample_count = n
                existing.computed_at = now
            else:
                db.add(ServiceMetricBaseline(
                    id=str(uuid4()),
                    service=service,
                    metric_name=metric_name,
                    hour_of_day=hour,
                    day_of_week=dow,
                    mean=mean,
                    stddev=stddev,
                    p50=p50,
                    p95=p95,
                    p99=p99,
                    sample_count=n,
                    window_days=WINDOW_DAYS,
                    computed_at=now,
                ))
            written += 1

        return written

    def get_baseline(
        self, service: str, metric_name: str, *, at: Optional[datetime] = None
    ) -> Optional[ServiceMetricBaseline]:
        """Return the baseline for a service+metric at a given hour, or None."""
        dt = at or datetime.utcnow()
        with SessionLocal() as db:
            return db.execute(
                select(ServiceMetricBaseline).where(
                    ServiceMetricBaseline.service == service,
                    ServiceMetricBaseline.metric_name == metric_name,
                    ServiceMetricBaseline.hour_of_day == dt.hour,
                    ServiceMetricBaseline.day_of_week == dt.weekday(),
                )
            ).scalar_one_or_none()

    def severity_for(
        self, service: str, metric_name: str, value: float
    ) -> tuple[str, float]:
        """Return (severity, ratio_vs_baseline) for a value.

        severity: 'ok' | 'warning' | 'critical'
        ratio: observed / mean baseline (1.0 = exactly at baseline)

        Falls back to ('unknown', 0.0) if no baseline exists yet.
        """
        baseline = self.get_baseline(service, metric_name)
        if baseline is None or baseline.sample_count < MIN_SAMPLES:
            return ("unknown", 0.0)

        if baseline.mean == 0:
            return ("ok", 1.0)

        ratio = value / baseline.mean
        threshold_warn = baseline.mean + SIGMA_WARN * baseline.stddev
        threshold_crit = baseline.mean + SIGMA_CRITICAL * baseline.stddev

        # For saturation metrics, anything above threshold is bad
        if value >= threshold_crit:
            return ("critical", ratio)
        if value >= threshold_warn:
            return ("warning", ratio)
        return ("ok", ratio)


baseline_engine = BaselineEngine()
