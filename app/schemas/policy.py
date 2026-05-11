"""Policy schema models for Cortex guardrail evaluation.

"""

from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class PolicyMatch(BaseModel):
    """Provides PolicyMatch behavior using local state or integrations and exposes structured outputs for callers."""

    service: Optional[str] = None
    tier: Optional[str] = None
    environment: Optional[str] = None


class PolicyLayer(BaseModel):
    """Provides PolicyLayer behavior using local state or integrations and exposes structured outputs for callers."""

    auto_mitigate: Optional[bool] = None
    escalation_required: Optional[bool] = None
    require_human_approval: Optional[bool] = None
    max_consecutive_actions: Optional[int] = Field(default=None, ge=1)
    allowed_actions: List[str] = Field(default_factory=list)
    denied_actions: List[str] = Field(default_factory=list)
    escalation_policy: Optional[str] = None


class ScopedPolicyRule(BaseModel):
    """Provides ScopedPolicyRule behavior using local state or integrations and exposes structured outputs for callers."""

    match: PolicyMatch
    settings: PolicyLayer


class MetricPolicyRule(BaseModel):
    """Provides MetricPolicyRule behavior using local state or integrations and exposes structured outputs for callers."""

    metric_name: str
    settings: PolicyLayer


class ActionPolicyRule(BaseModel):
    """Provides ActionPolicyRule behavior using local state or integrations and exposes structured outputs for callers."""

    action: str
    enabled: bool = True
    require_human_approval: Optional[bool] = None
    escalation_required: Optional[bool] = None


class PolicyDocument(BaseModel):
    """Provides PolicyDocument behavior using local state or integrations and exposes structured outputs for callers."""

    version: str
    defaults: PolicyLayer = Field(default_factory=PolicyLayer)
    global_settings: PolicyLayer = Field(default_factory=PolicyLayer, alias="global")
    severity_rules: Dict[str, PolicyLayer] = Field(default_factory=dict)
    scoped_rules: List[ScopedPolicyRule] = Field(default_factory=list)
    metric_rules: List[MetricPolicyRule] = Field(default_factory=list)
    action_rules: Dict[str, ActionPolicyRule] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class PolicyDecision(BaseModel):
    """Provides PolicyDecision behavior using local state or integrations and exposes structured outputs for callers."""

    policy_version: str
    allowed_actions: List[str] = Field(default_factory=list)
    blocked_actions: List[str] = Field(default_factory=list)
    auto_mitigate: bool = True
    escalation_required: bool = False
    require_human_approval: bool = False
    max_consecutive_actions: int = 1
    escalation_policy: Optional[str] = None