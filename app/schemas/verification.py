"""Verification schemas powering Heron Verify.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Literal, Optional


@dataclass
class MetricCheck:
    """Provides MetricCheck behavior using local state or integrations and exposes structured outputs for callers."""

    name: str
    baseline: float
    observed: float
    passed: bool
    direction: Literal["decrease", "increase"] = "decrease"
    min_delta: float = 0.0
    details: Optional[str] = None


@dataclass
class VerificationResult:
    """Provides VerificationResult behavior using local state or integrations and exposes structured outputs for callers."""

    decision_id: str
    action_id: Optional[str]
    status: Literal["pass", "fail", "timeout", "escalate"]
    success: bool
    checked_at: datetime
    confidence_delta: float = 0.0
    observation_window_seconds: int = 60
    escalation_required: bool = False
    summary: str = ""
    checks: List[MetricCheck] = field(default_factory=list)


def create_verification(
    decision_id: str,
    checks: List[MetricCheck],
    *,
    action_id: Optional[str] = None,
    status: Literal["pass", "fail", "timeout", "escalate"] = "pass",
    observation_window_seconds: int = 60,
    confidence_delta: float = 0.0,
    escalation_required: bool = False,
    summary: str = "",
) -> VerificationResult:
    """Creates verification using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    success = all(check.passed for check in checks)
    if status in {"fail", "timeout", "escalate"}:
        success = False
    return VerificationResult(
        decision_id=decision_id,
        action_id=action_id,
        status=status,
        success=success,
        checked_at=datetime.utcnow(),
        confidence_delta=confidence_delta,
        observation_window_seconds=observation_window_seconds,
        escalation_required=escalation_required,
        summary=summary,
        checks=checks,
    )