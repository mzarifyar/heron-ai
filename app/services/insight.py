"""Cortex Insight: static threshold anomaly detection.

"""

from __future__ import annotations

import json
import os
from typing import List, Optional

from ..core import get_logger, get_settings
from ..schemas.anomaly import Anomaly, ThresholdConfig, create_anomaly
from ..schemas.signal import BufferedSignal
from ..store.anomaly_store import AnomalyStore
from .core import core_service
from .explain import explain_service

logger = get_logger(__name__)


def _load_thresholds(thresholds_path: str) -> ThresholdConfig:
    """Loads thresholds using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    if os.path.exists(thresholds_path):
        with open(thresholds_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    else:
        # Fallback defaults
        data = {
            "payments-api": {
                "cpu_utilization": {"warn": 80.0, "critical": 90.0},
            }
        }
    return ThresholdConfig.from_dict(data)


class InsightService:
    """Provides InsightService behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, store: Optional[AnomalyStore] = None) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        settings = get_settings()
        self.store = store or AnomalyStore()
        self.thresholds = _load_thresholds(settings.thresholds_path)

    def _resolve_metric_name(self, buffered: BufferedSignal) -> str:
        """Resolves metric name using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        details = buffered.signal.details
        if isinstance(details, dict):
            metric_name = details.get("metric_name")
            if metric_name:
                return str(metric_name)
        # fallback to normalized summary
        return buffered.signal.summary.lower().replace(" ", "_")

    def evaluate(self, buffered: BufferedSignal) -> List[Anomaly]:
        """Builds evaluate using local state or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        if buffered.signal.metric is None:
            return []

        metric_name = self._resolve_metric_name(buffered)
        threshold = self.thresholds.get_threshold(
            buffered.context.service,
            metric_name,
            tier=buffered.context.tier,
            environment=buffered.context.environment,
        )
        if not threshold:
            logger.debug(
                "No threshold configured",
                extra={"service": buffered.context.service, "metric": metric_name},
            )
            return []

        value = buffered.signal.metric.value
        triggered: List[Anomaly] = []

        if value >= threshold.critical:
            anomaly = create_anomaly(
                severity=threshold.critical_severity,
                buffered_signal=buffered,
                threshold=threshold.critical,
                observed_value=value,
                rationale=f"value {value} exceeded critical threshold {threshold.critical}",
                confidence=0.95,
            )
            triggered.append(anomaly)
        elif value >= threshold.warn:
            anomaly = create_anomaly(
                severity=threshold.warn_severity,
                buffered_signal=buffered,
                threshold=threshold.warn,
                observed_value=value,
                rationale=f"value {value} exceeded warning threshold {threshold.warn}",
                confidence=0.8,
            )
            triggered.append(anomaly)
        else:
            # P0: near-miss detection — within 10% of warn threshold but didn't breach
            if threshold.warn > 0:
                gap_pct = (threshold.warn - value) / threshold.warn * 100
                if 0 < gap_pct <= 10.0:
                    self._record_near_miss(
                        service=buffered.context.service,
                        region=buffered.context.region,
                        metric_name=metric_name,
                        peak_value=value,
                        threshold=threshold.warn,
                        gap_pct=round(gap_pct, 2),
                    )

        for anomaly in triggered:
            self.store.add(anomaly)
            logger.info(
                "Anomaly detected",
                extra={
                    "anomaly_id": str(anomaly.anomaly_id),
                    "severity": anomaly.severity,
                    "service": buffered.context.service,
                    "metric": metric_name,
                    "threshold": anomaly.threshold,
                    "value": value,
                },
            )
            explain_service.record_event(
                component="insight",
                event_type="anomaly.detected",
                message="Insight anomaly detected from threshold evaluation",
                metadata={
                    "service": buffered.context.service,
                    "environment": buffered.context.environment,
                    "region": buffered.context.region,
                    "metric": metric_name,
                    "severity": anomaly.severity,
                    "anomaly_id": str(anomaly.anomaly_id),
                    "threshold": anomaly.threshold,
                    "observed_value": value,
                },
                correlation_ids={"anomaly_id": str(anomaly.anomaly_id)},
                signal_id=buffered.signal.signal_id,
            )

        if triggered:
            try:
                core_service.evaluate(buffered, triggered)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Core planning failed for anomaly batch",
                    extra={"signal_id": buffered.signal.signal_id, "error": str(exc)},
                )

        return triggered

    def _record_near_miss(
        self,
        *,
        service: str,
        region: str,
        metric_name: str,
        peak_value: float,
        threshold: float,
        gap_pct: float,
    ) -> None:
        """Write a near-miss record to the DB — metric came close but didn't breach."""
        try:
            from uuid import uuid4
            from datetime import datetime
            from ..db.base import SessionLocal
            from ..db.models import NearMiss
            with SessionLocal() as db:
                db.add(NearMiss(
                    id=str(uuid4()),
                    service=service,
                    region=region,
                    metric_name=metric_name,
                    peak_value=round(peak_value, 4),
                    threshold=round(threshold, 4),
                    gap_percent=gap_pct,
                    detected_at=datetime.utcnow(),
                ))
                db.commit()
            logger.info(
                "Near-miss detected: service=%s metric=%s value=%.4f threshold=%.4f gap=%.1f%%",
                service, metric_name, peak_value, threshold, gap_pct,
            )
        except Exception as exc:
            logger.debug("NearMiss DB persist failed (non-critical): %s", exc)

    def list_recent(self, limit: int = 50) -> List[dict]:
        """Lists recent using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        return [item.to_dict() for item in self.store.list_recent(limit)]

    def clear(self) -> None:
        """Clears the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.store.clear()


insight_service = InsightService()