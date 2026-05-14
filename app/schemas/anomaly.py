"""Anomaly schemas for Heron Insight.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from .signal import BufferedSignal

AnomalySeverity = Literal["sev1", "sev2", "sev3", "info"]
AnomalyType = Literal["static_threshold_breach"]


@dataclass
class Anomaly:
    """Provides Anomaly behavior using local state or integrations and exposes structured outputs for callers."""

    anomaly_id: UUID
    severity: AnomalySeverity
    anomaly_type: AnomalyType
    confidence: float
    detected_at: datetime
    signal: BufferedSignal
    threshold: float
    observed_value: float
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        """Builds to dict using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        return {
            "anomaly_id": str(self.anomaly_id),
            "severity": self.severity,
            "anomaly_type": self.anomaly_type,
            "confidence": self.confidence,
            "detected_at": self.detected_at.isoformat(),
            "signal": self.signal.to_dict(),
            "threshold": self.threshold,
            "observed_value": self.observed_value,
            "rationale": self.rationale,
        }


@dataclass
class ThresholdDefinition:
    """Provides ThresholdDefinition behavior using local state or integrations and exposes structured outputs for callers."""

    warn: float
    critical: float
    warn_severity: AnomalySeverity = "sev3"
    critical_severity: AnomalySeverity = "sev2"
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThresholdDefinition":
        """Builds from dict using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if "warn" not in data or "critical" not in data:
            raise ValueError("threshold definition must include warn and critical")
        warn_severity = str(data.get("warn_severity", "sev3"))
        critical_severity = str(data.get("critical_severity", "sev2"))
        allowed = {"sev1", "sev2", "sev3", "info"}
        if warn_severity not in allowed:
            raise ValueError(f"unsupported warn severity: {warn_severity}")
        if critical_severity not in allowed:
            raise ValueError(f"unsupported critical severity: {critical_severity}")
        metadata = data.get("metadata", {})
        return cls(
            warn=float(data["warn"]),
            critical=float(data["critical"]),
            warn_severity=warn_severity,  # type: ignore[arg-type]
            critical_severity=critical_severity,  # type: ignore[arg-type]
            metadata=metadata if isinstance(metadata, dict) else {},
        )


@dataclass
class ThresholdConfig:
    """Provides ThresholdConfig behavior using local state or integrations and exposes structured outputs for callers."""

    items: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThresholdConfig":
        """Builds from dict using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        return cls(items=data if isinstance(data, dict) else {})

    def _extract_default_metrics(self, service_cfg: Any) -> Dict[str, Any]:
        """Extracts default metrics using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if not isinstance(service_cfg, dict):
            return {}
        metrics = service_cfg.get("metrics")
        if isinstance(metrics, dict):
            return metrics
        # Backward-compatible legacy shape:
        # {"service": {"metric_name": {"warn": ..., "critical": ...}}}
        candidate: Dict[str, Any] = {}
        for key, value in service_cfg.items():
            if key == "overrides":
                continue
            if isinstance(value, dict) and "warn" in value and "critical" in value:
                candidate[key] = value
        return candidate

    def _resolve_override(
        self,
        service_cfg: Any,
        metric_name: str,
        *,
        tier: Optional[str],
        environment: Optional[str],
    ) -> Optional[ThresholdDefinition]:
        """Resolves override using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if not isinstance(service_cfg, dict):
            return None
        overrides = service_cfg.get("overrides")
        if not isinstance(overrides, list):
            return None

        best_match: Optional[ThresholdDefinition] = None
        best_score = -1

        for override in overrides:
            if not isinstance(override, dict):
                continue
            override_tier = override.get("tier")
            override_environment = override.get("environment")
            if override_tier and override_tier != tier:
                continue
            if override_environment and override_environment != environment:
                continue

            metrics = override.get("metrics")
            if not isinstance(metrics, dict):
                continue
            definition = metrics.get(metric_name)
            if not isinstance(definition, dict):
                continue

            specificity = 0
            if override_tier:
                specificity += 1
            if override_environment:
                specificity += 1
            if specificity > best_score:
                best_match = ThresholdDefinition.from_dict(definition)
                best_score = specificity

        return best_match

    def get_threshold(
        self,
        service: str,
        metric_name: str,
        *,
        tier: Optional[str] = None,
        environment: Optional[str] = None,
    ) -> Optional[ThresholdDefinition]:
        """Gets threshold using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        # Try specific service first, then fall back to "default"
        service_cfg = self.items.get(service) or self.items.get("default")
        if service_cfg is None:
            return None

        override_match = self._resolve_override(
            service_cfg,
            metric_name,
            tier=tier,
            environment=environment,
        )
        if override_match:
            return override_match

        default_metrics = self._extract_default_metrics(service_cfg)
        definition = default_metrics.get(metric_name)
        if not isinstance(definition, dict):
            return None
        return ThresholdDefinition.from_dict(definition)


def create_anomaly(
    severity: AnomalySeverity,
    buffered_signal: BufferedSignal,
    threshold: float,
    observed_value: float,
    rationale: str,
    confidence: float = 0.8,
) -> Anomaly:
    """Creates anomaly using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    return Anomaly(
        anomaly_id=uuid4(),
        severity=severity,
        anomaly_type="static_threshold_breach",
        confidence=confidence,
        detected_at=datetime.utcnow(),
        signal=buffered_signal,
        threshold=threshold,
        observed_value=observed_value,
        rationale=rationale,
    )