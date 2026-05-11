"""Heron Core decision engine — LLM-powered with rule-based fallback."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import Dict, List, Optional

from ..core import get_logger
from ..schemas.anomaly import Anomaly
from ..schemas.decision import DecisionOutcome, DecisionPlan, DecisionStep, DecisionStatus
from ..schemas.signal import BufferedSignal
from .explain import explain_service
from .learn import learn_service
from .policy import policy_service
from ..config_control import control_plane_service
from .ai.decision_advisor import decision_advisor

logger = get_logger(__name__)

_SEVERITY_RANK = {"sev1": 4, "sev2": 3, "sev3": 2, "info": 1}


class DecisionEngine:
    """Provides DecisionEngine behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._plans: Dict[str, DecisionPlan] = {}
        self._outcomes: Dict[str, DecisionOutcome] = {}

    def _select_highest_severity(self, anomalies: List[Anomaly]) -> str:
        """Builds select highest severity using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        highest = "info"
        for anomaly in anomalies:
            if _SEVERITY_RANK.get(anomaly.severity, 0) > _SEVERITY_RANK.get(highest, 0):
                highest = anomaly.severity
        return highest

    def _build_steps(self, severity: str, buffered_signal: BufferedSignal) -> List[DecisionStep]:
        """Builds steps using local state or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        if severity == "sev1":
            return [
                DecisionStep(
                    action="page_on_call",
                    rationale="Critical anomaly requires immediate human response",
                    priority=10,
                    requires_approval=False,
                    parameters={"service": buffered_signal.context.service, "urgency": "immediate"},
                )
            ]
        if severity == "sev2":
            return [
                DecisionStep(
                    action="rollback_latest_deployment",
                    rationale="High-severity degradation often correlates with recent deploys",
                    priority=20,
                    requires_approval=True,
                    parameters={"service": buffered_signal.context.service},
                ),
                DecisionStep(
                    action="escalate_incident",
                    rationale="Escalate if rollback is blocked or unavailable",
                    priority=30,
                    requires_approval=False,
                    parameters={"service": buffered_signal.context.service},
                ),
            ]
        if severity == "sev3":
            return [
                DecisionStep(
                    action="restart_component",
                    rationale="Warning-level anomalies can often recover with safe restart",
                    priority=40,
                    requires_approval=False,
                    parameters={
                        "service": buffered_signal.context.service,
                        "component": buffered_signal.context.component or "unknown",
                    },
                )
            ]
        return [
            DecisionStep(
                action="observe_only",
                rationale="Informational anomalies are tracked without active mitigation",
                priority=100,
                requires_approval=False,
                parameters={"service": buffered_signal.context.service},
            )
        ]

    def evaluate(self, buffered_signal: BufferedSignal, anomalies: List[Anomaly]) -> DecisionPlan:
        """Builds evaluate using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        control_plane = control_plane_service.control_plane
        env_cfg = control_plane_service.get_environment(buffered_signal.context.environment)
        severity = self._select_highest_severity(anomalies)
        confidence = round(
            (sum(anomaly.confidence for anomaly in anomalies) / len(anomalies)) if anomalies else 0.5,
            3,
        )

        wait_window = {
            "sev1": 30,
            "sev2": 60,
            "sev3": 120,
            "info": 300,
        }.get(severity, 300)
        escalation_policy = {
            "sev1": "page_immediately",
            "sev2": "escalate_if_unverified",
            "sev3": "monitor_then_escalate",
            "info": "none",
        }.get(severity, "none")

        # ── Try LLM-powered decision first ────────────────────────────────
        llm_reasoning = ""
        llm_escalate  = False
        learn_scores  = learn_service.recommendations(
            service=buffered_signal.context.service, severity=severity
        )
        llm_result = decision_advisor.advise(
            anomalies=anomalies,
            buffered_signal=buffered_signal,
            severity=severity,
            learn_scores=learn_scores,
        )
        if llm_result is not None:
            steps, confidence, llm_reasoning, llm_escalate = llm_result
            logger.info(
                "LLM decision used: service=%s severity=%s confidence=%.2f",
                buffered_signal.context.service, severity, confidence,
            )
        else:
            steps = self._build_steps(severity, buffered_signal)
            logger.info(
                "Rule-based decision used: service=%s severity=%s",
                buffered_signal.context.service, severity,
            )
        # ── Control plane gate ─────────────────────────────────────────────
        if env_cfg is not None and not control_plane_service.is_service_enabled(
            buffered_signal.context.environment,
            "core",
        ):
            steps = [
                DecisionStep(
                    action="observe_only",
                    rationale="Control plane disables Core actions for this environment",
                    priority=100,
                    requires_approval=False,
                    parameters={
                        "service": buffered_signal.context.service,
                        "environment": buffered_signal.context.environment,
                    },
                )
            ]
        metric_name = None
        details = buffered_signal.signal.details
        if isinstance(details, dict):
            value = details.get("metric_name")
            if isinstance(value, str) and value:
                metric_name = value
        policy_decision = policy_service.evaluate(
            service=buffered_signal.context.service,
            tier=buffered_signal.context.tier,
            environment=buffered_signal.context.environment,
            severity=severity,
            metric_name=metric_name,
            candidate_actions=[step.action for step in steps],
        )
        allowed_actions = set(policy_decision.allowed_actions)
        filtered_steps: List[DecisionStep] = [
            step
            for step in steps
            if step.action in allowed_actions
        ]
        for step in filtered_steps:
            if policy_decision.require_human_approval:
                step.requires_approval = True
        initial_action_order = [step.action for step in filtered_steps]
        ranked_action_order = list(initial_action_order)

        if not filtered_steps:
            filtered_steps = [
                DecisionStep(
                    action="observe_only",
                    rationale="All candidate actions were blocked by policy",
                    priority=100,
                    requires_approval=False,
                    parameters={"service": buffered_signal.context.service},
                )
            ]
            initial_action_order = ["observe_only"]
            ranked_action_order = ["observe_only"]
        else:
            ranked_action_order = learn_service.rank_actions(
                service=buffered_signal.context.service,
                severity=severity,
                actions=initial_action_order,
            )
            if ranked_action_order != initial_action_order:
                grouped: Dict[str, List[DecisionStep]] = {}
                for step in filtered_steps:
                    grouped.setdefault(step.action, []).append(step)
                reordered: List[DecisionStep] = []
                for action_name in ranked_action_order:
                    reordered.extend(grouped.pop(action_name, []))
                for remainder in grouped.values():
                    reordered.extend(remainder)
                filtered_steps = reordered

        plan = DecisionPlan(
            decision_id=f"dec-{uuid.uuid4().hex[:10]}",
            reasoning_trace_id=f"trace-{uuid.uuid4().hex[:10]}",
            service=buffered_signal.context.service,
            severity=severity,
            confidence=confidence,
            wait_window_seconds=wait_window,
            escalation_policy=policy_decision.escalation_policy or escalation_policy,
            policy_version=policy_decision.policy_version,
            control_plane_version=control_plane.version,
            actions=filtered_steps,
            anomaly_ids=[str(anomaly.anomaly_id) for anomaly in anomalies],
        )
        self._plans[plan.decision_id] = plan
        logger.info(
            "Core decision plan generated",
            extra={
                "decision_id": plan.decision_id,
                "severity": plan.severity,
                "service": plan.service,
                "actions": len(plan.actions),
            },
        )
        explain_service.record_event(
            component="core",
            event_type="decision.created",
            message="Core decision plan generated",
            metadata={
                "decision_id": plan.decision_id,
                "severity": plan.severity,
                "service": plan.service,
                "actions": [step.action for step in plan.actions],
                "anomaly_ids": plan.anomaly_ids,
                "confidence": plan.confidence,
                "policy_version": plan.policy_version,
                "control_plane_version": plan.control_plane_version,
                "policy_blocked_actions": policy_decision.blocked_actions,
                "learn_ranked_actions_applied": ranked_action_order != initial_action_order,
                "learn_initial_actions": initial_action_order,
                "learn_ranked_actions": ranked_action_order,
                "environment": buffered_signal.context.environment,
                "region": buffered_signal.context.region,
            },
            signal_id=buffered_signal.signal.signal_id,
        )
        return plan

    def record_outcome(
        self,
        decision_id: str,
        *,
        status: DecisionStatus,
        applied_actions: Optional[List[str]] = None,
        notes: Optional[str] = None,
    ) -> DecisionOutcome:
        """Records outcome using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        outcome = DecisionOutcome(
            decision_id=decision_id,
            status=status,
            notes=notes,
            applied_actions=applied_actions or [],
        )
        self._outcomes[decision_id] = outcome
        logger.info(
            "Core decision outcome recorded",
            extra={"decision_id": decision_id, "status": status},
        )
        return outcome

    def get_plan(self, decision_id: str) -> Optional[DecisionPlan]:
        """Gets plan using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        return self._plans.get(decision_id)

    def list_recent_plans(self, limit: int = 20) -> List[Dict[str, object]]:
        """Lists recent plans using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        plans = list(self._plans.values())[-limit:]
        return [asdict(plan) for plan in plans]

    def get_outcome(self, decision_id: str) -> Optional[DecisionOutcome]:
        """Gets outcome using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        return self._outcomes.get(decision_id)

    def clear(self) -> None:
        """Clears the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._plans.clear()
        self._outcomes.clear()


core_service = DecisionEngine()