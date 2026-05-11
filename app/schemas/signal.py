"""Pydantic schemas for signal ingestion.

"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, validator


SignalType = Literal["metric", "event", "log"]


class SignalMetric(BaseModel):
    """Provides SignalMetric behavior using local state or integrations and exposes structured outputs for callers."""

    value: float
    unit: Optional[str] = None
    window_seconds: int = Field(default=60, ge=1, le=3600)


class SignalContext(BaseModel):
    """Provides SignalContext behavior using local state or integrations and exposes structured outputs for callers."""

    org_id: str = Field(default="default", description="Tenant/org identifier for multi-tenant isolation")
    service: str
    tier: Literal["frontend", "mid", "backend", "batch", "platform"]
    environment: Literal["dev", "test", "stage", "prod"]
    region: str
    component: Optional[str] = None
    labels: Dict[str, str] = Field(default_factory=dict)


class SignalPayload(BaseModel):
    """Provides SignalPayload behavior using local state or integrations and exposes structured outputs for callers."""

    signal_id: str = Field(..., description="Unique identifier from upstream collector")
    type: SignalType
    detected_at: datetime
    metric: Optional[SignalMetric] = None
    summary: str = Field(..., description="Short human-readable description")
    details: Dict[str, Any] = Field(default_factory=dict)

    @validator("metric", always=True)
    def validate_metric(cls, value: Optional[SignalMetric], values: Dict[str, Any]) -> Optional[SignalMetric]:
        """Validates metric using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        signal_type: SignalType = values.get("type")  # type: ignore[assignment]
        if signal_type == "metric" and value is None:
            raise ValueError("Metric signals must include metric payload")
        return value


class SignalIngestRequest(BaseModel):
    """Provides SignalIngestRequest behavior using local state or integrations and exposes structured outputs for callers."""

    source: str  # e.g. "jira", "alert-source", "kubernetes", "prometheus", "demo"
    context: SignalContext
    signals: List[SignalPayload]

    @validator("signals")
    def validate_signals(cls, value: List[SignalPayload]) -> List[SignalPayload]:
        """Validates signals using local state or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        if not value:
            raise ValueError("At least one signal is required")
        return value


class SignalIngestResponse(BaseModel):
    """Provides SignalIngestResponse behavior using local state or integrations and exposes structured outputs for callers."""

    accepted: int
    buffered: int
    dropped: int = 0
    message: str = "signals accepted"


class BufferedSignal(BaseModel):
    """Provides BufferedSignal behavior using local state or integrations and exposes structured outputs for callers."""

    context: SignalContext
    signal: SignalPayload
    annotations: Dict[str, Any] = Field(default_factory=dict)

    def dict(self, *args: Any, **kwargs: Any) -> Dict[str, Any]:
        """Builds dict using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        base = super().dict(*args, **kwargs)
        merged = {
            **base["signal"],
            "context": base["context"],
        }
        if self.annotations:
            merged["annotations"] = self.annotations
        return merged