"""Cortex Reflex action execution service.

"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Protocol

from ..core import get_logger
from ..schemas.action import ActionAttempt, ActionExecution, create_execution
from ..schemas.decision import DecisionPlan, DecisionStep
from .explain import explain_service
from utils.logging_mode import get_activity_logger, is_logging_mode_enabled

logger = get_logger(__name__)

from app.core.paths import config as _cfg, data as _dat
DEFAULT_ACTIONS_PATH = Path(_cfg("actions.yaml"))


class ActionExecutor(Protocol):
    """Provides ActionExecutor behavior using local state or integrations and exposes structured outputs for callers."""
    def execute(self, *, command: str, timeout_seconds: int, dry_run: bool, parameters: Dict[str, object]) -> Dict[str, object]:
        """Builds execute using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        ...


class CommandExecutor:
    """Provides CommandExecutor behavior using local state or integrations and exposes structured outputs for callers."""
    def execute(self, *, command: str, timeout_seconds: int, dry_run: bool, parameters: Dict[str, object]) -> Dict[str, object]:
        """Builds execute using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if dry_run:
            return {"success": True, "details": "dry_run", "executor": "command", "command": command}
        return {"success": True, "details": "executed", "executor": "command", "command": command}


class ApiExecutor:
    """Provides ApiExecutor behavior using local state or integrations and exposes structured outputs for callers."""
    def execute(self, *, command: str, timeout_seconds: int, dry_run: bool, parameters: Dict[str, object]) -> Dict[str, object]:
        """Builds execute using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if dry_run:
            return {"success": True, "details": "dry_run", "executor": "api", "command": command}
        return {"success": True, "details": "sent", "executor": "api", "command": command}


class WorkflowExecutor:
    """Provides WorkflowExecutor behavior using local state or integrations and exposes structured outputs for callers."""
    def execute(self, *, command: str, timeout_seconds: int, dry_run: bool, parameters: Dict[str, object]) -> Dict[str, object]:
        """Builds execute using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if dry_run:
            return {"success": True, "details": "dry_run", "executor": "workflow", "command": command}
        return {"success": True, "details": "recorded", "executor": "workflow", "command": command}


def _load_yaml(path: Path) -> Dict[str, object]:
    """Loads yaml using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        import yaml  # type: ignore
    except Exception as exc:  # pragma: no cover - defensive
        raise RuntimeError("PyYAML is required for action catalog loading") from exc

    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError("action catalog must contain a mapping")
    return data


class ReflexService:
    """Provides ReflexService behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, actions_path: Path | None = None) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.actions_path = actions_path or DEFAULT_ACTIONS_PATH
        self.catalog = self._load_catalog(self.actions_path)
        self.executors: Dict[str, ActionExecutor] = {
            "command": CommandExecutor(),
            "api": ApiExecutor(),
            "workflow": WorkflowExecutor(),
        }
        self._history: Dict[str, List[ActionExecution]] = {}

    def _load_catalog(self, path: Path) -> Dict[str, object]:
        """Loads catalog using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if not path.exists():
            logger.warning("Action catalog missing at %s; using empty catalog", path)
            return {"defaults": {"retries": 0, "timeout_seconds": 30, "cooldown_seconds": 0}, "actions": {}}
        return _load_yaml(path)

    def refresh_catalog(self) -> Dict[str, object]:
        """Builds refresh catalog using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        self.catalog = self._load_catalog(self.actions_path)
        return self.catalog

    def _render_command(self, template: str, step: DecisionStep, plan: DecisionPlan) -> str:
        """Renders command using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        rendered = template
        replacements = {"service": plan.service, **{k: str(v) for k, v in step.parameters.items()}}
        for key, value in replacements.items():
            rendered = rendered.replace(f"{{{key}}}", value)
        return rendered

    def _action_def(self, action_name: str) -> Dict[str, object]:
        """Builds action def using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        defaults = self.catalog.get("defaults", {})
        actions = self.catalog.get("actions", {})
        action_cfg = {}
        if isinstance(actions, dict):
            action_cfg = actions.get(action_name, {}) or {}
        merged = dict(defaults if isinstance(defaults, dict) else {})
        if isinstance(action_cfg, dict):
            merged.update(action_cfg)
        return merged

    def _execute_single(
        self,
        *,
        plan: DecisionPlan,
        step: DecisionStep,
        dry_run: bool,
    ) -> ActionExecution:
        """Builds execute single using local writes or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        action_id = f"act-{uuid.uuid4().hex[:10]}"
        action_cfg = self._action_def(step.action)
        command_template = str(action_cfg.get("command", step.action))
        command = self._render_command(command_template, step, plan)
        retries = int(action_cfg.get("retries", 0))
        timeout_seconds = int(action_cfg.get("timeout_seconds", 30))
        cooldown_seconds = int(action_cfg.get("cooldown_seconds", 0))
        executor_name = str(action_cfg.get("type", "command"))
        executor = self.executors.get(executor_name, self.executors["workflow"])

        execution = create_execution(
            action_id,
            command,
            action_name=step.action,
            decision_id=plan.decision_id,
            dry_run=dry_run,
            executor=executor_name,
            metadata={"timeout_seconds": timeout_seconds},
        )
        execution.cooldown_seconds = cooldown_seconds

        first_attempt = execution.attempts[0]
        result = executor.execute(
            command=command,
            timeout_seconds=timeout_seconds,
            dry_run=dry_run,
            parameters=step.parameters,
        )
        first_attempt.finished_at = datetime.utcnow()
        first_attempt.success = bool(result.get("success"))
        first_attempt.details = str(result.get("details", ""))
        first_attempt.output = result

        attempt_count = 0
        while not first_attempt.success and attempt_count < retries:
            attempt_count += 1
            retry_attempt = ActionAttempt(
                command=command,
                executor=executor_name,
                started_at=datetime.utcnow(),
            )
            retry_result = executor.execute(
                command=command,
                timeout_seconds=timeout_seconds,
                dry_run=dry_run,
                parameters=step.parameters,
            )
            retry_attempt.finished_at = datetime.utcnow()
            retry_attempt.success = bool(retry_result.get("success"))
            retry_attempt.details = str(retry_result.get("details", ""))
            retry_attempt.output = retry_result
            execution.attempts.append(retry_attempt)
            if retry_attempt.success:
                break

        execution.status = "succeeded" if any(attempt.success for attempt in execution.attempts) else "failed"
        execution.finished_at = datetime.utcnow()
        return execution

    def execute_plan(
        self,
        plan: DecisionPlan,
        *,
        dry_run: Optional[bool] = None,
        max_actions: Optional[int] = None,
    ) -> List[ActionExecution]:
        """Builds execute plan using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        resolved_dry_run = is_logging_mode_enabled() if dry_run is None else dry_run
        executions: List[ActionExecution] = []
        cap = max_actions if max_actions is not None else len(plan.actions)
        for index, step in enumerate(plan.actions):
            if index >= cap:
                skipped = ActionExecution(
                    action_id=f"act-{uuid.uuid4().hex[:10]}",
                    action_name=step.action,
                    decision_id=plan.decision_id,
                    status="skipped",
                    dry_run=resolved_dry_run,
                    metadata={"reason": "max_actions_cap"},
                )
                skipped.started_at = datetime.utcnow()
                skipped.finished_at = skipped.started_at
                executions.append(skipped)
                continue

            execution = self._execute_single(plan=plan, step=step, dry_run=resolved_dry_run)
            executions.append(execution)

            action_cfg = self._action_def(step.action)
            if execution.status == "failed":
                fallback = action_cfg.get("fallback", [])
                if isinstance(fallback, list):
                    for fallback_action in fallback:
                        fallback_step = DecisionStep(
                            action=str(fallback_action),
                            rationale=f"Fallback after {step.action} failure",
                            priority=step.priority + 1,
                            requires_approval=step.requires_approval,
                            parameters=dict(step.parameters),
                        )
                        executions.append(self._execute_single(plan=plan, step=fallback_step, dry_run=resolved_dry_run))

        self._history[plan.decision_id] = executions
        activity_logger = get_activity_logger()
        if activity_logger is not None:
            activity_logger.append(
                {
                    "event": "reflex.actions.executed",
                    "decision_id": plan.decision_id,
                    "dry_run": resolved_dry_run,
                    "actions": [
                        {
                            "action_id": item.action_id,
                            "action_name": item.action_name,
                            "status": item.status,
                            "attempts": len(item.attempts),
                        }
                        for item in executions
                    ],
                }
            )
        explain_service.record_event(
            component="reflex",
            event_type="actions.executed",
            message="Reflex executed decision plan actions",
            metadata={
                "decision_id": plan.decision_id,
                "actions": [item.action_name for item in executions],
                "statuses": [item.status for item in executions],
                "dry_run": resolved_dry_run,
                "service": plan.service,
                "severity": plan.severity,
            },
        )
        return executions

    def get_execution_history(self, decision_id: str) -> List[ActionExecution]:
        """Gets execution history using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        return list(self._history.get(decision_id, []))

    def clear(self) -> None:
        """Clears the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._history.clear()


reflex_service = ReflexService()