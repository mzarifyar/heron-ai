"""Decision/action outcome verification service.

"""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional

from ..core import get_logger
from ..schemas.verification import MetricCheck, VerificationResult, create_verification
from .core import core_service
from .explain import explain_service
from .learn import learn_service

logger = get_logger(__name__)


class VerificationService:
    """Provides VerificationService behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, failure_escalation_threshold: int = 2) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.failure_escalation_threshold = failure_escalation_threshold
        self._results_by_decision: Dict[str, List[VerificationResult]] = defaultdict(list)
        self._action_success_history: Dict[str, Deque[bool]] = defaultdict(lambda: deque(maxlen=100))
        self._consecutive_failures: Dict[str, int] = defaultdict(int)

    def _compare_metric(
        self,
        metric_name: str,
        baseline: float,
        observed: float,
        *,
        direction: str = "decrease",
        min_delta: float = 0.0,
    ) -> MetricCheck:
        """Builds compare metric using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        if direction == "increase":
            passed = (observed - baseline) >= min_delta
            details = f"expected increase >= {min_delta}"
        else:
            passed = (baseline - observed) >= min_delta
            details = f"expected decrease >= {min_delta}"
        return MetricCheck(
            name=metric_name,
            baseline=baseline,
            observed=observed,
            passed=passed,
            direction="increase" if direction == "increase" else "decrease",
            min_delta=min_delta,
            details=details,
        )

    def verify(
        self,
        *,
        decision_id: str,
        action_id: Optional[str],
        baseline_metrics: Dict[str, float],
        observed_metrics: Dict[str, float],
        metric_policies: Optional[Dict[str, Dict[str, object]]] = None,
        observation_window_seconds: int = 60,
        timed_out: bool = False,
        service: str = "unknown",
    ) -> VerificationResult:
        """Builds verify using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        metric_policies = metric_policies or {}
        checks: List[MetricCheck] = []

        if timed_out:
            result = create_verification(
                decision_id,
                checks,
                action_id=action_id,
                status="timeout",
                observation_window_seconds=observation_window_seconds,
                confidence_delta=-0.3,
                escalation_required=True,
                summary="Verification timed out before sufficient telemetry was collected",
            )
            self._record_result(result, service=service)
            return result

        for metric_name, baseline in baseline_metrics.items():
            observed = observed_metrics.get(metric_name)
            if observed is None:
                checks.append(
                    MetricCheck(
                        name=metric_name,
                        baseline=baseline,
                        observed=baseline,
                        passed=False,
                        details="missing observed metric",
                    )
                )
                continue
            policy = metric_policies.get(metric_name, {})
            direction = str(policy.get("direction", "decrease"))
            min_delta = float(policy.get("min_delta", 0.0))
            checks.append(
                self._compare_metric(
                    metric_name,
                    baseline,
                    observed,
                    direction=direction,
                    min_delta=min_delta,
                )
            )

        all_passed = bool(checks) and all(check.passed for check in checks)
        status = "pass" if all_passed else "fail"
        confidence_delta = 0.15 if all_passed else -0.2
        summary = "Verification checks passed" if all_passed else "Verification checks failed"

        result = create_verification(
            decision_id,
            checks,
            action_id=action_id,
            status=status,  # type: ignore[arg-type]
            observation_window_seconds=observation_window_seconds,
            confidence_delta=confidence_delta,
            escalation_required=False,
            summary=summary,
        )
        self._record_result(result, service=service)
        return result

    def _record_result(self, result: VerificationResult, *, service: str = "unknown") -> None:
        """Records result using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._results_by_decision[result.decision_id].append(result)
        action_key = result.action_id or "unknown"
        self._action_success_history[action_key].append(result.success)

        if result.success:
            self._consecutive_failures[action_key] = 0
        else:
            self._consecutive_failures[action_key] += 1
            if self._consecutive_failures[action_key] >= self.failure_escalation_threshold:
                result.escalation_required = True
                result.status = "escalate"
                result.summary = (
                    f"{result.summary}. Escalation required after "
                    f"{self._consecutive_failures[action_key]} consecutive failures."
                )

        plan = core_service.get_plan(result.decision_id)
        learn_service_name = service
        learn_severity = "unknown"
        learn_action = (result.action_id or "").strip()
        if plan is not None:
            learn_service_name = plan.service or learn_service_name
            learn_severity = plan.severity or learn_severity
            planned_actions = [item.action for item in plan.actions if item.action]
            if not learn_action and planned_actions:
                learn_action = planned_actions[0]
            elif learn_action and learn_action not in planned_actions and planned_actions:
                learn_action = planned_actions[0]
        if not learn_action:
            learn_action = "unknown"
        try:
            learn_service.observe_action_outcome(
                service=learn_service_name,
                severity=learn_severity,
                action=learn_action,
                success=result.success,
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "Learn observation failed",
                extra={
                    "decision_id": result.decision_id,
                    "action": learn_action,
                    "service": learn_service_name,
                    "severity": learn_severity,
                    "error": str(exc),
                },
            )

        # P0: persist outcome to DB so Intelligence page has live data
        try:
            from uuid import uuid4
            from datetime import datetime
            from ..db.base import SessionLocal
            from ..db.models import LearnOutcome as DBLearnOutcome
            with SessionLocal() as db:
                db.add(DBLearnOutcome(
                    id=str(uuid4()),
                    incident_id=result.decision_id,
                    action_type=learn_action,
                    service=learn_service_name,
                    severity=learn_severity,
                    outcome="success" if result.success else "failed",
                    confidence_delta=0.05 if result.success else -0.03,
                    recorded_at=datetime.utcnow(),
                ))
                db.commit()
        except Exception as exc:
            logger.debug("LearnOutcome DB persist failed (non-critical): %s", exc)

        logger.info(
            "Verification result recorded",
            extra={
                "decision_id": result.decision_id,
                "action_id": result.action_id,
                "service": service,
                "status": result.status,
                "success": result.success,
                "escalation_required": result.escalation_required,
            },
        )
        explain_service.record_event(
            component="verify",
            event_type="verification.completed",
            message=result.summary or "Verification completed",
            metadata={
                "decision_id": result.decision_id,
                "action_id": result.action_id,
                "status": result.status,
                "success": result.success,
                "escalation_required": result.escalation_required,
                "learn_action": learn_action,
                "learn_service": learn_service_name,
                "learn_severity": learn_severity,
                "checks": [
                    {
                        "name": check.name,
                        "baseline": check.baseline,
                        "observed": check.observed,
                        "passed": check.passed,
                        "direction": check.direction,
                        "min_delta": check.min_delta,
                    }
                    for check in result.checks
                ],
            },
        )

    def get_results(self, decision_id: str) -> List[VerificationResult]:
        """Gets results using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        return list(self._results_by_decision.get(decision_id, []))

    def action_success_rate(self, action_id: str) -> float:
        """Builds action success rate using local reads or integration calls and returns a numeric value (e.g., 1.0), may raise ValueError for bad input while dependency errors may bubble."""
        history = self._action_success_history.get(action_id)
        if not history:
            return 0.0
        return sum(1 for item in history if item) / len(history)

    def clear(self) -> None:
        """Clears the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._results_by_decision.clear()
        self._action_success_history.clear()
        self._consecutive_failures.clear()


verify_service = VerificationService()