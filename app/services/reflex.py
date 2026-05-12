"""Cortex Reflex action execution service.

"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
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
DEFAULT_POLICY_PATH = Path(_cfg("policy.yaml"))


# ---------------------------------------------------------------------------
# Policy gate
# ---------------------------------------------------------------------------

class _PolicyGate:
    """Reads the live_execution block from policy.yaml and answers whether a
    given action is allowed to run live in the current environment."""

    def __init__(self, policy_path: Path) -> None:
        self._path = policy_path
        self._live: Dict[str, object] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            import yaml  # type: ignore
            with self._path.open("r", encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
            self._live = cfg.get("live_execution", {}) or {}
        except Exception as exc:
            logger.warning("Failed to load policy from %s: %s", self._path, exc)

    def is_live_allowed(self, action_name: str, environment: str) -> bool:
        """Return True only when all three gates pass: global enabled, this
        environment is listed, and this action is opted in."""
        if not self._live.get("enabled", False):
            return False
        env_map = self._live.get("environments", {}) or {}
        if not env_map.get(environment, False):
            return False
        per_action = self._live.get("per_action", {}) or {}
        return bool(per_action.get(action_name, False))

    def refresh(self) -> None:
        self._load()


# ---------------------------------------------------------------------------
# Executor protocol and implementations
# ---------------------------------------------------------------------------

class ActionExecutor(Protocol):
    """Provides ActionExecutor behavior using local state or integrations and exposes structured outputs for callers."""
    def execute(self, *, command: str, timeout_seconds: int, dry_run: bool, parameters: Dict[str, object]) -> Dict[str, object]:
        """Builds execute using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        ...


class CommandExecutor:
    """Runs shell commands. In live mode kubectl invocations are dispatched via
    the kubernetes integration with optional kubeconfig resolution."""

    def execute(self, *, command: str, timeout_seconds: int, dry_run: bool, parameters: Dict[str, object]) -> Dict[str, object]:
        if dry_run:
            return {"success": True, "details": "dry_run", "executor": "command", "command": command}

        try:
            parts = shlex.split(command)
        except ValueError:
            parts = command.split()

        if not parts:
            return {"success": False, "details": "empty_command", "executor": "command", "command": command}

        if parts[0] == "kubectl":
            return self._exec_kubectl(parts, timeout_seconds, parameters)

        return self._exec_generic(parts, command, timeout_seconds)

    def _exec_kubectl(self, parts: List[str], timeout_seconds: int, parameters: Dict[str, object]) -> Dict[str, object]:
        if not shutil.which("kubectl"):
            return {"success": False, "details": "kubectl_not_found", "executor": "command", "command": " ".join(parts)}

        namespace = str(parameters.get("namespace", "default"))
        cluster = str(parameters.get("cluster", "") or os.environ.get("HERON_KUBE_CLUSTER", ""))

        cmd = list(parts)

        # Inject --kubeconfig when a cluster name is known
        if cluster:
            try:
                from app.integrations.kubernetes import get_kubeconfig_for_cluster
                kc = get_kubeconfig_for_cluster(cluster)
                if kc:
                    cmd = ["kubectl", "--kubeconfig", kc] + cmd[1:]
            except Exception as exc:
                logger.warning("kubeconfig resolution failed for cluster %s: %s", cluster, exc)

        # Inject -n <namespace> when not already present
        cmd_str = " ".join(cmd)
        if "-n " not in cmd_str and "--namespace" not in cmd_str:
            kc_idx = cmd.index("--kubeconfig") if "--kubeconfig" in cmd else -1
            insert = (kc_idx + 2) if kc_idx >= 0 else 1
            cmd = cmd[:insert] + ["-n", namespace] + cmd[insert:]

        return self._run_subprocess(cmd, timeout_seconds)

    def _exec_generic(self, parts: List[str], original: str, timeout_seconds: int) -> Dict[str, object]:
        return self._run_subprocess(parts, timeout_seconds, original_command=original)

    @staticmethod
    def _run_subprocess(cmd: List[str], timeout_seconds: int, original_command: Optional[str] = None) -> Dict[str, object]:
        display = original_command or " ".join(cmd)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds)
            return {
                "success": proc.returncode == 0,
                "details": "executed" if proc.returncode == 0 else f"exit_{proc.returncode}",
                "executor": "command",
                "command": " ".join(cmd),
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "returncode": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "details": f"timeout_after_{timeout_seconds}s", "executor": "command", "command": display}
        except FileNotFoundError:
            return {"success": False, "details": f"command_not_found:{cmd[0]}", "executor": "command", "command": display}
        except Exception as exc:
            return {"success": False, "details": str(exc), "executor": "command", "command": display}


class ApiExecutor:
    """Fires HTTP calls or routes internal URI schemes (incident://, pager://)
    to the real Slack/PagerDuty integrations in live mode."""

    def execute(self, *, command: str, timeout_seconds: int, dry_run: bool, parameters: Dict[str, object]) -> Dict[str, object]:
        if dry_run:
            return {"success": True, "details": "dry_run", "executor": "api", "command": command}

        if "://" in command:
            scheme, rest = command.split("://", 1)
            if scheme == "pager":
                return self._dispatch_pager(rest, parameters)
            if scheme == "incident":
                return self._dispatch_incident(rest, parameters)

        # Generic HTTP POST
        return self._dispatch_http(command, timeout_seconds, parameters)

    @staticmethod
    def _dispatch_pager(path: str, parameters: Dict[str, object]) -> Dict[str, object]:
        try:
            from app.integrations import pagerduty
            service = path.split("/")[-1]
            result = pagerduty.trigger_incident(
                target=str(parameters.get("target", service)),
                message=str(parameters.get("message", f"Heron autonomous action for {service}")),
                severity=str(parameters.get("severity", "sev2")),
                service=service,
                environment=str(parameters.get("environment", os.environ.get("CORTEX_ENV", "unknown"))),
                incident_id=str(parameters.get("incident_id", "")),
            )
            return {"success": result.get("ok", False), "details": result.get("status", "dispatched"), "executor": "api", "result": result}
        except Exception as exc:
            return {"success": False, "details": str(exc), "executor": "api", "command": f"pager://{path}"}

    @staticmethod
    def _dispatch_incident(path: str, parameters: Dict[str, object]) -> Dict[str, object]:
        try:
            from app.integrations import slack
            service = path.split("/")[-1]
            result = slack.send_message(
                target=str(parameters.get("target", service)),
                message=str(parameters.get("message", f"Heron escalation triggered for {service}")),
            )
            return {"success": result.get("ok", False), "details": result.get("status", "dispatched"), "executor": "api", "result": result}
        except Exception as exc:
            return {"success": False, "details": str(exc), "executor": "api", "command": f"incident://{path}"}

    @staticmethod
    def _dispatch_http(url: str, timeout_seconds: int, parameters: Dict[str, object]) -> Dict[str, object]:
        try:
            import requests  # type: ignore
            resp = requests.post(url, json=dict(parameters), timeout=timeout_seconds)
            return {
                "success": resp.ok,
                "details": f"http_{resp.status_code}",
                "executor": "api",
                "status_code": resp.status_code,
            }
        except Exception as exc:
            return {"success": False, "details": str(exc), "executor": "api", "command": url}


class WorkflowExecutor:
    """Triggers named workflow definitions. 'noop' is a no-op in both modes;
    unknown workflows log a warning and return success so the plan continues."""

    def execute(self, *, command: str, timeout_seconds: int, dry_run: bool, parameters: Dict[str, object]) -> Dict[str, object]:
        if dry_run:
            return {"success": True, "details": "dry_run", "executor": "workflow", "command": command}
        if command == "noop":
            return {"success": True, "details": "noop", "executor": "workflow", "command": command}
        logger.warning("WorkflowExecutor: no handler for workflow '%s' — treating as noop", command)
        return {"success": True, "details": "workflow_unregistered", "executor": "workflow", "command": command}


# ---------------------------------------------------------------------------
# YAML loading helper
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# ReflexService
# ---------------------------------------------------------------------------

class ReflexService:
    """Provides ReflexService behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, actions_path: Path | None = None, policy_path: Path | None = None) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.actions_path = actions_path or DEFAULT_ACTIONS_PATH
        self.catalog = self._load_catalog(self.actions_path)
        self._policy = _PolicyGate(policy_path or DEFAULT_POLICY_PATH)
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
        self._policy.refresh()
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

    def _resolve_dry_run(self, action_name: str, base_dry_run: bool) -> bool:
        """Return the effective dry_run flag for a single action.

        Logging mode and an explicit dry_run=True always win.  Otherwise the
        policy gate decides — if it says live is allowed, we flip to False.
        """
        if base_dry_run:
            return True
        environment = os.environ.get("CORTEX_ENV", "unknown")
        return not self._policy.is_live_allowed(action_name, environment)

    def _take_snapshot(self, service: str, action_id: str, parameters: Dict[str, object]) -> Optional[str]:
        """Capture the current deployment manifest to /tmp before a destructive
        action so an operator can restore the previous state if needed."""
        if not shutil.which("kubectl"):
            return None

        namespace = str(parameters.get("namespace", "default"))
        cluster = str(parameters.get("cluster", "") or os.environ.get("HERON_KUBE_CLUSTER", ""))

        cmd = ["kubectl"]
        if cluster:
            try:
                from app.integrations.kubernetes import get_kubeconfig_for_cluster
                kc = get_kubeconfig_for_cluster(cluster)
                if kc:
                    cmd += ["--kubeconfig", kc]
            except Exception:
                pass
        cmd += ["-n", namespace, "get", f"deployment/{service}", "-o", "json"]

        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode == 0 and proc.stdout.strip():
                snap_path = f"/tmp/heron_snap_{action_id}_{service}.json"
                with open(snap_path, "w", encoding="utf-8") as fh:
                    fh.write(proc.stdout)
                logger.info("Pre-action snapshot saved to %s", snap_path)
                return snap_path
        except Exception as exc:
            logger.warning("Snapshot failed for %s: %s", service, exc)
        return None

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

        # Per-action policy check: logging mode or explicit dry_run override wins,
        # otherwise the policy gate may permit live execution for this action.
        effective_dry_run = self._resolve_dry_run(step.action, dry_run)

        execution = create_execution(
            action_id,
            command,
            action_name=step.action,
            decision_id=plan.decision_id,
            dry_run=effective_dry_run,
            executor=executor_name,
            metadata={"timeout_seconds": timeout_seconds},
        )
        execution.cooldown_seconds = cooldown_seconds

        # Pre-action snapshot for reversible kubectl actions
        if not effective_dry_run and action_cfg.get("rollback_snapshot"):
            snap = self._take_snapshot(plan.service, action_id, step.parameters)
            if snap:
                execution.metadata["snapshot_path"] = snap

        first_attempt = execution.attempts[0]
        result = executor.execute(
            command=command,
            timeout_seconds=timeout_seconds,
            dry_run=effective_dry_run,
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
                dry_run=effective_dry_run,
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
        # Base dry_run: logging mode forces dry, explicit override respected,
        # otherwise False (each action will consult the policy gate individually).
        if dry_run is not None:
            base_dry_run = dry_run
        elif is_logging_mode_enabled():
            base_dry_run = True
        else:
            base_dry_run = False

        executions: List[ActionExecution] = []
        cap = max_actions if max_actions is not None else len(plan.actions)
        for index, step in enumerate(plan.actions):
            if index >= cap:
                skipped = ActionExecution(
                    action_id=f"act-{uuid.uuid4().hex[:10]}",
                    action_name=step.action,
                    decision_id=plan.decision_id,
                    status="skipped",
                    dry_run=base_dry_run,
                    metadata={"reason": "max_actions_cap"},
                )
                skipped.started_at = datetime.utcnow()
                skipped.finished_at = skipped.started_at
                executions.append(skipped)
                continue

            execution = self._execute_single(plan=plan, step=step, dry_run=base_dry_run)
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
                        executions.append(self._execute_single(plan=plan, step=fallback_step, dry_run=base_dry_run))

        self._history[plan.decision_id] = executions
        activity_logger = get_activity_logger()
        if activity_logger is not None:
            activity_logger.append(
                {
                    "event": "reflex.actions.executed",
                    "decision_id": plan.decision_id,
                    "dry_run": base_dry_run,
                    "actions": [
                        {
                            "action_id": item.action_id,
                            "action_name": item.action_name,
                            "status": item.status,
                            "attempts": len(item.attempts),
                            "dry_run": item.dry_run,
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
                "dry_run": base_dry_run,
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
