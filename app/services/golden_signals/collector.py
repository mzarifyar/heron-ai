"""Golden Signals collector — aggregates raw signals into per-service metrics.

Runs as a background thread every 60 seconds. Reads recent signals from the DB,
computes the four golden signals per service, writes edge metrics, and triggers
baseline recomputation every 30 minutes.
"""

from __future__ import annotations

import statistics
import threading
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ...db.base import SessionLocal
from ...db.models import Signal, ServiceEdgeMetric
from ...core import get_logger
from .baseline import baseline_engine

logger = get_logger(__name__)

COLLECTION_INTERVAL_SECONDS = 60
BASELINE_RECOMPUTE_INTERVAL_SECONDS = 1800   # 30 minutes
WINDOW_SECONDS = 120                          # aggregate last 2 minutes


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(int(len(s) * pct), len(s) - 1)
    return s[idx]


class GoldenSignalsCollector:
    """Background collector for the four golden signals per service."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._last_baseline_compute = datetime.utcnow() - timedelta(hours=1)

    def start(self) -> None:
        logger.info("Golden signals collector starting")
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="golden-signals-collector", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _loop(self) -> None:
        while not self._stop.wait(timeout=COLLECTION_INTERVAL_SECONDS):
            try:
                self._collect()
                self._maybe_recompute_baselines()
            except Exception as exc:
                logger.warning("Golden signals collection error: %s", exc)

    def _collect(self) -> None:
        since = datetime.utcnow() - timedelta(seconds=WINDOW_SECONDS)

        with SessionLocal() as db:
            # Pull all signals in the collection window
            rows = db.execute(
                select(Signal.service, Signal.metric_name, Signal.value, Signal.timestamp)
                .where(Signal.timestamp >= since)
                .order_by(Signal.service, Signal.metric_name)
            ).all()

            if not rows:
                return

            # Group by service
            by_service: dict[str, dict[str, list[float]]] = {}
            for service, metric_name, value, _ in rows:
                by_service.setdefault(service, {}).setdefault(metric_name, []).append(value)

            now = datetime.utcnow()

            for service, metrics in by_service.items():
                self._write_golden_signals(db, service, metrics, now)

            db.commit()

    def _write_golden_signals(
        self,
        db: Session,
        service: str,
        metrics: dict[str, list[float]],
        ts: datetime,
    ) -> None:
        """Compute aggregated golden signals and write edge metrics."""

        # ── Latency ─────────────────────────────────────────────────────────
        latency_vals = (
            metrics.get("latency_p99_ms") or
            metrics.get("latency_ms") or
            metrics.get("response_time_ms") or []
        )
        if latency_vals:
            p99 = _percentile(latency_vals, 0.99)
            p95 = _percentile(latency_vals, 0.95)
            p50 = _percentile(latency_vals, 0.50)
            sev, ratio = baseline_engine.severity_for(service, "latency_p99_ms", p99)
            logger.debug(
                "Latency: service=%s p99=%.1fms severity=%s ratio=%.2f",
                service, p99, sev, ratio,
            )

        # ── Traffic ──────────────────────────────────────────────────────────
        rps_vals = (
            metrics.get("request_rate_rps") or
            metrics.get("rps") or []
        )
        rps = statistics.mean(rps_vals) if rps_vals else 0.0
        if rps == 0.0:
            # Zero traffic is itself an anomaly — log but don't fire immediately
            logger.debug("Zero traffic detected for service=%s", service)

        # ── Errors ───────────────────────────────────────────────────────────
        error_vals = (
            metrics.get("error_rate") or
            metrics.get("error_rate_pct") or []
        )
        error_rate = statistics.mean(error_vals) if error_vals else 0.0
        sev_err, _ = baseline_engine.severity_for(service, "error_rate", error_rate)

        # ── Saturation (connection pool is the critical one) ─────────────────
        pool_vals = (
            metrics.get("connection_pool_pct") or
            metrics.get("db_pool_utilization") or []
        )
        pool_pct = max(pool_vals) if pool_vals else 0.0
        if pool_pct > 80.0:
            logger.warning(
                "Connection pool saturation: service=%s pool=%.1f%%",
                service, pool_pct,
            )

        # Write edge metrics (source=service, dest=downstream)
        # In a real eBPF scenario, source/dest would be distinct.
        # For now write a self-edge carrying the aggregated signals.
        db.add(ServiceEdgeMetric(
            id=str(uuid4()),
            source_service=service,
            dest_service=service,
            cluster="default",
            timestamp=ts,
            p50_ms=_percentile(latency_vals, 0.50) if latency_vals else 0.0,
            p95_ms=_percentile(latency_vals, 0.95) if latency_vals else 0.0,
            p99_ms=_percentile(latency_vals, 0.99) if latency_vals else 0.0,
            rps=rps,
            error_rate=error_rate,
        ))

    def _maybe_recompute_baselines(self) -> None:
        now = datetime.utcnow()
        if (now - self._last_baseline_compute).total_seconds() >= BASELINE_RECOMPUTE_INTERVAL_SECONDS:
            logger.info("Recomputing golden signal baselines")
            baseline_engine.compute_all()
            self._last_baseline_compute = now

    def get_current_signals(self, service: str) -> dict[str, Any]:
        """Return current golden signal values for a service.

        Uses progressive time windows: 2min → 1hr → 7days so seeded/demo
        data always shows even without a live signal stream.
        """
        windows = [WINDOW_SECONDS * 2, 3600, 86400 * 7]
        rows = []
        with SessionLocal() as db:
            for window in windows:
                since = datetime.utcnow() - timedelta(seconds=window)
                rows = db.execute(
                    select(Signal.metric_name, Signal.value)
                    .where(Signal.service == service, Signal.timestamp >= since)
                ).all()
                if rows:
                    break

        by_metric: dict[str, list[float]] = {}
        for metric_name, value in rows:
            by_metric.setdefault(metric_name, []).append(value)

        def _agg(keys: list[str]) -> list[float]:
            for k in keys:
                if k in by_metric:
                    return by_metric[k]
            return []

        latency = _agg(["latency_p99_ms", "latency_ms"])
        errors   = _agg(["error_rate", "error_rate_pct"])
        traffic  = _agg(["request_rate_rps", "rps"])
        cpu      = _agg(["cpu_utilization"])
        memory   = _agg(["memory_utilization"])
        pool     = _agg(["connection_pool_pct"])

        def _with_baseline(metric_name: str, value: float) -> dict:
            sev, ratio = baseline_engine.severity_for(service, metric_name, value)
            bl = baseline_engine.get_baseline(service, metric_name)
            return {
                "current": round(value, 4),
                "baseline_mean": round(bl.mean, 4) if bl else None,
                "baseline_p99": round(bl.p99, 4) if bl else None,
                "ratio_vs_baseline": round(ratio, 3),
                "severity": sev,
            }

        return {
            "service": service,
            "timestamp": datetime.utcnow().isoformat(),
            "latency": {
                "p50_ms": _percentile(latency, 0.50),
                "p95_ms": _percentile(latency, 0.95),
                "p99_ms": _percentile(latency, 0.99),
                **_with_baseline("latency_p99_ms", _percentile(latency, 0.99)),
            },
            "traffic": {
                "rps": round(statistics.mean(traffic), 2) if traffic else 0.0,
                "zero_traffic": len(traffic) == 0 or max(traffic, default=0) == 0,
                **_with_baseline("request_rate_rps", statistics.mean(traffic) if traffic else 0.0),
            },
            "errors": {
                "rate_pct": round(statistics.mean(errors) * 100, 3) if errors else 0.0,
                **_with_baseline("error_rate", statistics.mean(errors) if errors else 0.0),
            },
            "saturation": {
                "cpu_pct": round(max(cpu, default=0.0) * 100, 1),
                "memory_pct": round(max(memory, default=0.0) * 100, 1),
                "connection_pool_pct": round(max(pool, default=0.0), 1),
                "cpu_severity": baseline_engine.severity_for(service, "cpu_utilization", max(cpu, default=0))[0],
                "memory_severity": baseline_engine.severity_for(service, "memory_utilization", max(memory, default=0))[0],
                "pool_severity": "critical" if max(pool, default=0) > 90 else
                                 "warning" if max(pool, default=0) > 80 else "ok",
            },
        }


golden_signals_collector = GoldenSignalsCollector()
