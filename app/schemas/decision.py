"""Decision schemas used by Heron Core planning.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional


@dataclass
class DecisionRecommendation:
    """Provides DecisionRecommendation behavior using local state or integrations and exposes structured outputs for callers."""

    action: str
    rationale: str
    confidence: float = 0.0


@dataclass
class DecisionImpact:
    """Provides DecisionImpact behavior using local state or integrations and exposes structured outputs for callers."""

    metric: str
    expected_change: float
    unit: Optional[str] = None


@dataclass
class Decision:
    """Provides Decision behavior using local state or integrations and exposes structured outputs for callers."""

    decision_id: str
    recommendations: List[DecisionRecommendation] = field(default_factory=list)
    impacts: List[DecisionImpact] = field(default_factory=list)
    status: str = "draft"


DecisionStatus = Literal["planned", "in_progress", "succeeded", "failed", "skipped"]


@dataclass
class DecisionStep:
    """Provides DecisionStep behavior using local state or integrations and exposes structured outputs for callers."""

    action: str
    rationale: str
    priority: int = 100
    requires_approval: bool = False
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DecisionPlan:
    """Provides DecisionPlan behavior using local state or integrations and exposes structured outputs for callers."""

    decision_id: str
    reasoning_trace_id: str
    service: str
    severity: str
    confidence: float
    wait_window_seconds: int
    escalation_policy: str
    policy_version: Optional[str] = None
    control_plane_version: Optional[str] = None
    actions: List[DecisionStep] = field(default_factory=list)
    anomaly_ids: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class DecisionOutcome:
    """Provides DecisionOutcome behavior using local state or integrations and exposes structured outputs for callers."""

    decision_id: str
    status: DecisionStatus
    notes: Optional[str] = None
    applied_actions: List[str] = field(default_factory=list)
    recorded_at: datetime = field(default_factory=datetime.utcnow)