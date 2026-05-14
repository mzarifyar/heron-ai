"""Policy loading and evaluation service for Heron guardrails.

"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Iterable, List, Optional

from ..core import get_logger
from ..schemas.policy import (
    ActionPolicyRule,
    PolicyDecision,
    PolicyDocument,
    PolicyLayer,
    PolicyMatch,
)

logger = get_logger(__name__)

from app.core.paths import config as _cfg, data as _dat
DEFAULT_POLICY_PATH = Path(_cfg("policy.yaml"))


def _load_yaml(path: Path) -> Dict[str, object]:
    """Loads yaml using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError("PyYAML is required for policy loading") from exc

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("policy file must contain a mapping")
    return data


def _merge_layers(base: PolicyLayer, override: PolicyLayer) -> PolicyLayer:
    """Merges layers using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    payload = base.model_dump()
    data = override.model_dump(exclude_unset=True)
    for key, value in data.items():
        if key in ("allowed_actions", "denied_actions"):
            continue
        payload[key] = value

    # keep accumulated sets while preserving stable order
    allowed = list(dict.fromkeys((payload.get("allowed_actions") or []) + override.allowed_actions))
    denied = list(dict.fromkeys((payload.get("denied_actions") or []) + override.denied_actions))
    payload["allowed_actions"] = allowed
    payload["denied_actions"] = denied
    return PolicyLayer.model_validate(payload)


class PolicyEngine:
    """Provides PolicyEngine behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, policy_path: Path | None = None) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.policy_path = policy_path or DEFAULT_POLICY_PATH
        self.document = self._load_document(self.policy_path)

    def _load_document(self, path: Path) -> PolicyDocument:
        """Loads document using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if not path.exists():
            logger.warning("Policy file missing at %s; using defaults", path)
            return PolicyDocument(version="local-default")
        payload = _load_yaml(path)
        return PolicyDocument.model_validate(payload)

    def refresh(self) -> PolicyDocument:
        """Builds refresh using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        self.document = self._load_document(self.policy_path)
        return self.document

    def _matches(self, match: PolicyMatch, *, service: str, tier: str, environment: str) -> bool:
        """Builds matches using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        if match.service and match.service != service:
            return False
        if match.tier and match.tier != tier:
            return False
        if match.environment and match.environment != environment:
            return False
        return True

    def _resolve_layer(
        self,
        *,
        service: str,
        tier: str,
        environment: str,
        severity: str,
        metric_name: Optional[str],
    ) -> PolicyLayer:
        """Resolves layer using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        layer = self.document.defaults
        layer = _merge_layers(layer, self.document.global_settings)
        severity_layer = self.document.severity_rules.get(severity)
        if severity_layer:
            layer = _merge_layers(layer, severity_layer)

        for scoped in self.document.scoped_rules:
            if self._matches(scoped.match, service=service, tier=tier, environment=environment):
                layer = _merge_layers(layer, scoped.settings)

        if metric_name:
            for metric_rule in self.document.metric_rules:
                if metric_rule.metric_name == metric_name:
                    layer = _merge_layers(layer, metric_rule.settings)
        return layer

    def evaluate(
        self,
        *,
        service: str,
        tier: str,
        environment: str,
        severity: str,
        metric_name: Optional[str],
        candidate_actions: Iterable[str],
    ) -> PolicyDecision:
        """Builds evaluate using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        candidates = list(candidate_actions)
        layer = self._resolve_layer(
            service=service,
            tier=tier,
            environment=environment,
            severity=severity,
            metric_name=metric_name,
        )
        decision = PolicyDecision(
            policy_version=self.document.version,
            auto_mitigate=layer.auto_mitigate if layer.auto_mitigate is not None else True,
            escalation_required=layer.escalation_required if layer.escalation_required is not None else False,
            require_human_approval=layer.require_human_approval if layer.require_human_approval is not None else False,
            max_consecutive_actions=layer.max_consecutive_actions or 1,
            escalation_policy=layer.escalation_policy,
        )

        allowed_set = set(layer.allowed_actions)
        denied_set = set(layer.denied_actions)

        allowed: List[str] = []
        blocked: List[str] = []
        for action in candidates:
            blocked_reason = False
            if allowed_set and action not in allowed_set:
                blocked_reason = True
            if action in denied_set:
                blocked_reason = True

            action_rule: Optional[ActionPolicyRule] = self.document.action_rules.get(action)
            if action_rule and not action_rule.enabled:
                blocked_reason = True
            if blocked_reason:
                blocked.append(action)
                continue

            if action_rule and action_rule.require_human_approval is not None:
                if action_rule.require_human_approval:
                    decision.require_human_approval = True
            if action_rule and action_rule.escalation_required is not None:
                decision.escalation_required = action_rule.escalation_required
            allowed.append(action)

        if decision.max_consecutive_actions > 0:
            allowed = allowed[: decision.max_consecutive_actions]
            blocked.extend(action for action in candidates if action not in allowed and action not in blocked)

        decision.allowed_actions = list(dict.fromkeys(allowed))
        decision.blocked_actions = list(dict.fromkeys(blocked))
        return decision


policy_service = PolicyEngine()