"""Execute diagnostics workflows in safe/invasive/overwatch passes.

"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List
import json
import os
import re
import shlex
import shutil
import subprocess
import time

from app.integrations.kubernetes import get_kubeconfig_for_cluster
from app.services.diagnostics_strategies import k8s as k8s_strategies

SAFE_COMMAND_PREFIX_RE = re.compile(r"^\s*kubectl\b", re.IGNORECASE)
UNSAFE_SHELL_TOKEN_RE = re.compile(r"(;|&&|\|\||`|\$\(|\n|\r|>|<)")
SAFE_PIPE_SUFFIX_RE = re.compile(r"^\s*(egrep|grep|tail|awk)\b", re.IGNORECASE)
ERROR_SNIPPET_RE = re.compile(
    r"(error|exception|fatal|panic|crash|segfault|oom|outofmemory|killed|evicted|liveness|readiness|"
    r"imagepullbackoff|crashloopbackoff|back-off|timeout|timed out|connection refused|tls|x509|permission denied|"
    r"unauthorized|forbidden)",
    re.IGNORECASE,
)


class DiagnosticsRunner:
    """Provides DiagnosticsRunner behavior using local state or integrations and exposes structured outputs for callers."""

    @staticmethod
    def _bool_env(name: str, default: bool) -> bool:
        """Builds bool env using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        raw = (os.getenv(name) or "").strip().lower()
        if not raw:
            return default
        return raw in {"1", "true", "yes", "on"}

    @staticmethod
    def _safe_command(command: str) -> bool:
        """Builds safe command using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        text = (command or "").strip()
        if not text or not SAFE_COMMAND_PREFIX_RE.match(text):
            return False
        if UNSAFE_SHELL_TOKEN_RE.search(text):
            return False
        if "|" not in text:
            return True
        parts = text.split("|")
        if len(parts) != 2:
            return False
        left = parts[0].strip()
        right = parts[1].strip()
        if not SAFE_COMMAND_PREFIX_RE.match(left):
            return False
        if not SAFE_PIPE_SUFFIX_RE.match(right):
            return False
        return True

    @staticmethod
    def _inject_kubeconfig(command: str, kubeconfig: str | None) -> str:
        """Builds inject kubeconfig using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        text = (command or "").strip()
        if not text or not kubeconfig or not SAFE_COMMAND_PREFIX_RE.match(text):
            return text
        quoted = shlex.quote(kubeconfig)
        return re.sub(r"^\s*kubectl\b", f"kubectl --kubeconfig {quoted}", text, count=1, flags=re.IGNORECASE)

    @staticmethod
    def _workload_hint(pod_name: str) -> str:
        """Builds workload hint using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        name = (pod_name or "").strip()
        if not name:
            return ""
        parts = name.split("-")
        if len(parts) >= 3:
            return "-".join(parts[:-2])
        if len(parts) == 2:
            return parts[0]
        return name

    @staticmethod
    def _is_evicted_pod(pod: Dict[str, Any]) -> bool:
        """Builds evicted check using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        reason = str(pod.get("reason") or "").strip().lower()
        waiting = str(pod.get("waiting_reason") or "").strip().lower()
        return "evicted" in reason or "evicted" in waiting

    @staticmethod
    def _pod_matches_target(pod: Dict[str, Any], targets: set[str]) -> bool:
        """Builds pod target match using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        ns = str(pod.get("namespace") or "").strip()
        name = str(pod.get("name") or "").strip()
        if not ns or not name:
            return False
        return f"{ns}/{name}" in targets

    @staticmethod
    def _parse_csv_set(value: str | None) -> set[str]:
        """Builds csv parser using local state or integration calls and returns a set result (e.g., {"a"}), may raise ValueError for bad input while dependency errors may bubble."""
        return {item.strip() for item in str(value or "").split(",") if item.strip()}

    def _select_pod_down_targets(self, unhealthy_pods: List[Dict[str, str]]) -> Dict[str, Any]:
        """Builds pod-down target list using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        target_pods = self._parse_csv_set(os.getenv("HERON_POD_DOWN_TARGET_PODS_CSV"))
        target_namespaces = self._parse_csv_set(os.getenv("HERON_POD_DOWN_TARGET_NAMESPACES_CSV"))
        selected = list(unhealthy_pods)
        policy = "auto_detected_unhealthy"
        if target_namespaces:
            selected = [
                pod
                for pod in selected
                if str(pod.get("namespace") or "").strip() in target_namespaces
            ]
            policy = "namespace_scoped_unhealthy"
        if target_pods:
            selected = [pod for pod in selected if self._pod_matches_target(pod, target_pods)]
            policy = "explicit_target_pods"
        return {"policy": policy, "targets": selected}

    def _select_invasive_targets(self, *, preview: Dict[str, Any], unhealthy_pods: List[Dict[str, str]]) -> Dict[str, Any]:
        """Builds invasive target list using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        rid = str(preview.get("runbook_id") or "").strip().lower()
        targets: List[Dict[str, str]] = list(unhealthy_pods)
        policy = "all_unhealthy"
        if rid in {
            "rbk-infrastructure-kubernetes-kubernetes-pod-evicted",
            "rbk-evicted-pod-cleanup",
        }:
            delete_all_non_running = self._bool_env("HERON_EVICTED_DELETE_ALL_NON_RUNNING", False)
            delete_evicted_only = self._bool_env("HERON_EVICTED_DELETE_EVICTED_ONLY", True)
            if delete_all_non_running:
                policy = "all_non_running"
            elif delete_evicted_only:
                policy = "evicted_only"
                targets = [pod for pod in unhealthy_pods if self._is_evicted_pod(pod)]
            else:
                policy = "disabled"
                targets = []
        return {"policy": policy, "targets": targets}

    def _resolve_kubeconfig(self, context: Dict[str, Any] | None) -> Dict[str, Any]:
        """Resolves kubeconfig using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if not isinstance(context, dict):
            return {"resolved": True, "cluster": "", "kubeconfig": None, "reason": "no_context"}
        cluster_name = str(context.get("cluster") or context.get("cluster_name") or "").strip()
        if not cluster_name:
            return {"resolved": True, "cluster": "", "kubeconfig": None, "reason": "no_cluster"}
        account_id = str(context.get("account_id") or "").strip() or None
        kubeconfig = get_kubeconfig_for_cluster(cluster_name, account_id=account_id)
        if kubeconfig:
            return {"resolved": True, "cluster": cluster_name, "kubeconfig": kubeconfig, "reason": "resolved"}
        require_cluster_context = self._bool_env("HERON_DIAGNOSTICS_REQUIRE_CLUSTER_CONTEXT", True)
        if require_cluster_context:
            return {
                "resolved": False,
                "cluster": cluster_name,
                "kubeconfig": None,
                "reason": "cluster_context_unresolved",
            }
        return {
            "resolved": True,
            "cluster": cluster_name,
            "kubeconfig": None,
            "reason": "cluster_context_unresolved_allowed",
        }

    @staticmethod
    def _run_shell(command: str, timeout_seconds: int) -> Dict[str, Any]:
        """Runs shell using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        started = time.time()
        proc = subprocess.run(  # noqa: S602
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        elapsed = int((time.time() - started) * 1000)
        return {
            "success": proc.returncode == 0,
            "return_code": proc.returncode,
            "stdout": (proc.stdout or "")[:16000],
            "stderr": (proc.stderr or "")[:16000],
            "duration_ms": elapsed,
        }

    @staticmethod
    def _error_snippets(text: str, *, max_lines: int = 60) -> List[str]:
        """Builds error snippets using local state or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        if not text:
            return []
        out: List[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if ERROR_SNIPPET_RE.search(line):
                out.append(line[:600])
                if len(out) >= max(1, max_lines):
                    break
        return out

    def _collect_pod_evidence(
        self,
        *,
        unhealthy_pods: List[Dict[str, str]],
        dry_run: bool,
        timeout_seconds: int,
        kubeconfig: str | None,
        namespace_scope: str | None,
    ) -> List[Dict[str, Any]]:
        """Collects pod evidence using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        limit = int((os.getenv("HERON_DIAGNOSTICS_SAFE_EVIDENCE_PODS") or "25").strip() or "25")
        log_tail_lines = int((os.getenv("HERON_DIAGNOSTICS_LOG_TAIL_LINES") or "300").strip() or "300")
        namespace_filter = (namespace_scope or "").strip()
        evidence: List[Dict[str, Any]] = []
        for pod in unhealthy_pods[: max(1, min(200, limit))]:
            ns = str(pod.get("namespace") or "").strip()
            name = str(pod.get("name") or "").strip()
            if not ns or not name:
                continue
            if namespace_filter and ns != namespace_filter:
                continue
            quoted_ns = shlex.quote(ns)
            quoted_name = shlex.quote(name)
            node = str(pod.get("node") or "").strip()
            quoted_node = shlex.quote(node) if node else ""

            commands = {
                "get_pod_wide": self._inject_kubeconfig(
                    f"kubectl get pod {quoted_name} -n {quoted_ns} -o wide",
                    kubeconfig,
                ),
                "get_pod_json": self._inject_kubeconfig(
                    f"kubectl get pod {quoted_name} -n {quoted_ns} -o json",
                    kubeconfig,
                ),
                "describe_pod": self._inject_kubeconfig(
                    f"kubectl describe pod {quoted_name} -n {quoted_ns}",
                    kubeconfig,
                ),
                "ns_events": self._inject_kubeconfig(
                    f"kubectl get events -n {quoted_ns} --sort-by=.lastTimestamp | tail -100",
                    kubeconfig,
                ),
                "logs_current_all": self._inject_kubeconfig(
                    f"kubectl logs {quoted_name} -n {quoted_ns} --all-containers --timestamps --tail={max(1, log_tail_lines)}",
                    kubeconfig,
                ),
                "logs_previous_all": self._inject_kubeconfig(
                    f"kubectl logs {quoted_name} -n {quoted_ns} --all-containers --timestamps --previous --tail={max(1, log_tail_lines)}",
                    kubeconfig,
                ),
                "owner_ref": self._inject_kubeconfig(
                    f"kubectl get pod {quoted_name} -n {quoted_ns} -o jsonpath='{{.metadata.ownerReferences[0].kind}} {{.metadata.ownerReferences[0].name}}'",
                    kubeconfig,
                ),
            }
            if quoted_node:
                commands["describe_node"] = self._inject_kubeconfig(
                    f"kubectl describe node {quoted_node}",
                    kubeconfig,
                )

            if dry_run:
                evidence.append(
                    {
                        "namespace": ns,
                        "name": name,
                        "phase": str(pod.get("phase") or ""),
                        "reason": str(pod.get("reason") or ""),
                        "node": node,
                        "status": "planned",
                        "commands": commands,
                    }
                )
                continue

            cmd_results: Dict[str, Any] = {}
            for key, command in commands.items():
                cmd_results[key] = self._run_shell(command, timeout_seconds=timeout_seconds)

            logs_current = str((cmd_results.get("logs_current_all") or {}).get("stdout") or "")
            logs_previous = str((cmd_results.get("logs_previous_all") or {}).get("stdout") or "")
            evidence.append(
                {
                    "namespace": ns,
                    "name": name,
                    "phase": str(pod.get("phase") or ""),
                    "reason": str(pod.get("reason") or ""),
                    "node": node,
                    "status": "collected",
                    "commands": commands,
                    "results": cmd_results,
                    "error_snippets": {
                        "current": self._error_snippets(logs_current),
                        "previous": self._error_snippets(logs_previous),
                    },
                }
            )
        return evidence

    def _collect_unhealthy_pods(
        self,
        timeout_seconds: int,
        *,
        kubeconfig: str | None = None,
        namespace_scope: str | None = None,
    ) -> Dict[str, Any]:
        """Collects unhealthy pods using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        cmd = self._inject_kubeconfig("kubectl get pods -A -o json", kubeconfig)
        namespace_filter = (namespace_scope or "").strip()
        if not shutil.which("kubectl"):
            return {"success": False, "command": cmd, "error": "kubectl_not_found", "pods": []}
        result = self._run_shell(cmd, timeout_seconds=timeout_seconds)
        if not result.get("success"):
            return {"success": False, "command": cmd, "error": result.get("stderr") or "kubectl_failed", "pods": []}
        try:
            payload = json.loads(result.get("stdout") or "{}")
        except json.JSONDecodeError:
            return {"success": False, "command": cmd, "error": "invalid_json", "pods": []}
        items = payload.get("items") if isinstance(payload, dict) else []
        pods: List[Dict[str, str]] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            spec = item.get("spec") if isinstance(item.get("spec"), dict) else {}
            ns = str(metadata.get("namespace") or "").strip()
            name = str(metadata.get("name") or "").strip()
            phase = str(status.get("phase") or "").strip()
            if not ns or not name:
                continue
            if namespace_filter and ns != namespace_filter:
                continue
            if phase in {"Running", "Succeeded", "Completed"}:
                continue
            reason = str(status.get("reason") or "").strip()
            container_statuses = status.get("containerStatuses") if isinstance(status.get("containerStatuses"), list) else []
            waiting_reasons = []
            for container in container_statuses:
                if not isinstance(container, dict):
                    continue
                state = container.get("state") if isinstance(container.get("state"), dict) else {}
                waiting = state.get("waiting") if isinstance(state.get("waiting"), dict) else {}
                waiting_reason = str(waiting.get("reason") or "").strip()
                if waiting_reason:
                    waiting_reasons.append(waiting_reason)
            pods.append(
                {
                    "namespace": ns,
                    "name": name,
                    "phase": phase,
                    "reason": reason,
                    "node": str(spec.get("nodeName") or "").strip(),
                    "waiting_reason": ",".join(waiting_reasons[:3]),
                    "workload_hint": self._workload_hint(name),
                }
            )
        return {"success": True, "command": cmd, "pods": pods}

    def _collect_quota_candidates(
        self,
        *,
        timeout_seconds: int,
        kubeconfig: str | None = None,
        namespace_scope: str | None = None,
        threshold_percent: int = 95,
        target_quota_name: str | None = None,
    ) -> Dict[str, Any]:
        """Collects quota candidates using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        ns = (namespace_scope or "").strip()
        if ns:
            cmd = self._inject_kubeconfig(f"kubectl get resourcequota -n {shlex.quote(ns)} -o json", kubeconfig)
        else:
            cmd = self._inject_kubeconfig("kubectl get resourcequota -A -o json", kubeconfig)
        if not shutil.which("kubectl"):
            return {"success": False, "command": cmd, "error": "kubectl_not_found", "candidates": []}
        result = self._run_shell(cmd, timeout_seconds=timeout_seconds)
        if not result.get("success"):
            return {"success": False, "command": cmd, "error": result.get("stderr") or "kubectl_failed", "candidates": []}
        try:
            payload = json.loads(result.get("stdout") or "{}")
        except json.JSONDecodeError:
            return {"success": False, "command": cmd, "error": "invalid_json", "candidates": []}

        quota_filter = (target_quota_name or "").strip()
        candidates: List[Dict[str, Any]] = []
        items = payload.get("items") if isinstance(payload, dict) else []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            spec = item.get("spec") if isinstance(item.get("spec"), dict) else {}
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            hard_map = spec.get("hard") if isinstance(spec.get("hard"), dict) else {}
            used_map = status.get("used") if isinstance(status.get("used"), dict) else {}
            name = str(metadata.get("name") or "").strip()
            namespace = str(metadata.get("namespace") or "").strip()
            if not name or not namespace:
                continue
            if quota_filter and name != quota_filter:
                continue
            hard_raw = str(hard_map.get("pods") or "").strip()
            used_raw = str(used_map.get("pods") or "").strip()
            if not hard_raw.isdigit() or not used_raw.isdigit():
                continue
            hard = int(hard_raw)
            used = int(used_raw)
            if hard <= 0:
                continue
            percent = (used * 100.0) / hard
            if percent < max(1, threshold_percent):
                continue
            candidates.append(
                {
                    "namespace": namespace,
                    "quota_name": name,
                    "used_pods": used,
                    "hard_pods": hard,
                    "percent": round(percent, 2),
                }
            )
        return {"success": True, "command": cmd, "candidates": candidates}

    def _collect_readonly_nodes(
        self,
        *,
        timeout_seconds: int,
        kubeconfig: str | None = None,
        node_selector: str | None = None,
        target_nodes_csv: str | None = None,
    ) -> Dict[str, Any]:
        """Collects read-only node candidates using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        targets = [item.strip() for item in str(target_nodes_csv or "").split(",") if item.strip()]
        if targets:
            nodes = [{"name": name, "condition_status": "TARGETED"} for name in targets]
            return {"success": True, "nodes": nodes, "source": "target_nodes_csv"}

        cmd = self._inject_kubeconfig("kubectl get nodes -o json", kubeconfig)
        if not shutil.which("kubectl"):
            return {"success": False, "command": cmd, "error": "kubectl_not_found", "nodes": []}
        result = self._run_shell(cmd, timeout_seconds=timeout_seconds)
        if not result.get("success"):
            return {"success": False, "command": cmd, "error": result.get("stderr") or "kubectl_failed", "nodes": []}
        try:
            payload = json.loads(result.get("stdout") or "{}")
        except json.JSONDecodeError:
            return {"success": False, "command": cmd, "error": "invalid_json", "nodes": []}

        selector_names: set[str] | None = None
        selector = str(node_selector or "").strip()
        if selector:
            sel_cmd = self._inject_kubeconfig(f"kubectl get nodes -l {shlex.quote(selector)} -o json", kubeconfig)
            sel_result = self._run_shell(sel_cmd, timeout_seconds=timeout_seconds)
            if sel_result.get("success"):
                try:
                    sel_payload = json.loads(sel_result.get("stdout") or "{}")
                    selector_names = {
                        str(item.get("metadata", {}).get("name") or "").strip()
                        for item in sel_payload.get("items", [])
                        if isinstance(item, dict)
                    }
                except json.JSONDecodeError:
                    selector_names = None

        nodes: List[Dict[str, str]] = []
        items = payload.get("items") if isinstance(payload, dict) else []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            name = str(metadata.get("name") or "").strip()
            if not name:
                continue
            if selector_names is not None and name not in selector_names:
                continue
            conditions = status.get("conditions") if isinstance(status.get("conditions"), list) else []
            readonly_true = any(
                isinstance(cond, dict)
                and str(cond.get("type") or "") == "NodePvcOrRootMountReadonly"
                and str(cond.get("status") or "") == "True"
                for cond in conditions
            )
            if not readonly_true:
                continue
            nodes.append({"name": name, "condition_status": "NodePvcOrRootMountReadonly=True"})
        return {"success": True, "command": cmd, "nodes": nodes, "source": "node_condition"}

    def _collect_node_readonly_evidence(
        self,
        *,
        nodes: List[Dict[str, str]],
        dry_run: bool,
        timeout_seconds: int,
        kubeconfig: str | None,
    ) -> List[Dict[str, Any]]:
        """Collects node read-only evidence using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        limit = int((os.getenv("HERON_DIAGNOSTICS_SAFE_EVIDENCE_NODES") or "25").strip() or "25")
        evidence: List[Dict[str, Any]] = []
        for node in nodes[: max(1, min(200, limit))]:
            name = str(node.get("name") or "").strip()
            if not name:
                continue
            qn = shlex.quote(name)
            commands = {
                "get_node_wide": self._inject_kubeconfig(f"kubectl get node {qn} -o wide", kubeconfig),
                "get_node_json": self._inject_kubeconfig(f"kubectl get node {qn} -o json", kubeconfig),
                "describe_node": self._inject_kubeconfig(f"kubectl describe node {qn}", kubeconfig),
                "pods_on_node": self._inject_kubeconfig(
                    f"kubectl get pods -A -o wide --field-selector spec.nodeName={qn}",
                    kubeconfig,
                ),
                "pods_on_node_non_running": self._inject_kubeconfig(
                    f"kubectl get pods -A -o wide --field-selector spec.nodeName={qn},status.phase!=Running",
                    kubeconfig,
                ),
                "events_signals": self._inject_kubeconfig(
                    f"kubectl get events -A --sort-by=.lastTimestamp | egrep '{qn}|ReadOnly|readonly|mount|NodePvcOrRootMountReadonly|Evict|Evicted|Failed|error|NotReady|Unhealthy|BackOff'",
                    kubeconfig,
                ),
            }
            if dry_run:
                evidence.append(
                    {
                        "name": name,
                        "condition_status": str(node.get("condition_status") or ""),
                        "status": "planned",
                        "commands": commands,
                    }
                )
                continue
            cmd_results: Dict[str, Any] = {}
            for key, command in commands.items():
                cmd_results[key] = self._run_shell(command, timeout_seconds=timeout_seconds)
            describe_stdout = str((cmd_results.get("describe_node") or {}).get("stdout") or "")
            events_stdout = str((cmd_results.get("events_signals") or {}).get("stdout") or "")
            evidence.append(
                {
                    "name": name,
                    "condition_status": str(node.get("condition_status") or ""),
                    "status": "collected",
                    "commands": commands,
                    "results": cmd_results,
                    "error_snippets": {
                        "describe": self._error_snippets(describe_stdout, max_lines=80),
                        "events": self._error_snippets(events_stdout, max_lines=80),
                    },
                }
            )
        return evidence

    def _collect_maintenance_nodes(
        self,
        *,
        timeout_seconds: int,
        kubeconfig: str | None = None,
        node_selector: str | None = None,
        target_nodes_csv: str | None = None,
        condition_regex: str | None = None,
    ) -> Dict[str, Any]:
        """Collects maintenance node candidates using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        targets = [item.strip() for item in str(target_nodes_csv or "").split(",") if item.strip()]
        if targets:
            nodes = [{"name": name, "reason": "TARGETED"} for name in targets]
            return {"success": True, "nodes": nodes, "source": "target_nodes_csv"}

        cmd = self._inject_kubeconfig("kubectl get nodes -o json", kubeconfig)
        if not shutil.which("kubectl"):
            return {"success": False, "command": cmd, "error": "kubectl_not_found", "nodes": []}
        result = self._run_shell(cmd, timeout_seconds=timeout_seconds)
        if not result.get("success"):
            return {"success": False, "command": cmd, "error": result.get("stderr") or "kubectl_failed", "nodes": []}
        try:
            payload = json.loads(result.get("stdout") or "{}")
        except json.JSONDecodeError:
            return {"success": False, "command": cmd, "error": "invalid_json", "nodes": []}

        selector_names: set[str] | None = None
        selector = str(node_selector or "").strip()
        if selector:
            sel_cmd = self._inject_kubeconfig(f"kubectl get nodes -l {shlex.quote(selector)} -o json", kubeconfig)
            sel_result = self._run_shell(sel_cmd, timeout_seconds=timeout_seconds)
            if sel_result.get("success"):
                try:
                    sel_payload = json.loads(sel_result.get("stdout") or "{}")
                    selector_names = {
                        str(item.get("metadata", {}).get("name") or "").strip()
                        for item in sel_payload.get("items", [])
                        if isinstance(item, dict)
                    }
                except json.JSONDecodeError:
                    selector_names = None

        condition_re = str(condition_regex or "").strip()
        condition_pattern = re.compile(condition_re, re.IGNORECASE) if condition_re else None

        nodes: List[Dict[str, str]] = []
        items = payload.get("items") if isinstance(payload, dict) else []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            name = str(metadata.get("name") or "").strip()
            if not name:
                continue
            if selector_names is not None and name not in selector_names:
                continue
            conditions = status.get("conditions") if isinstance(status.get("conditions"), list) else []
            bad_true_types = [
                str(cond.get("type") or "").strip()
                for cond in conditions
                if isinstance(cond, dict)
                and str(cond.get("status") or "") == "True"
                and str(cond.get("type") or "") not in {"Ready", "NetworkUnavailable"}
            ]
            if not bad_true_types:
                continue
            if condition_pattern:
                bad_true_types = [ctype for ctype in bad_true_types if condition_pattern.search(ctype)]
                if not bad_true_types:
                    continue
            nodes.append({"name": name, "reason": f"ConditionTrue:{','.join(sorted(set(bad_true_types)))}"})
        return {"success": True, "command": cmd, "nodes": nodes, "source": "node_condition"}

    def _collect_node_maintenance_evidence(
        self,
        *,
        nodes: List[Dict[str, str]],
        dry_run: bool,
        timeout_seconds: int,
        kubeconfig: str | None,
    ) -> List[Dict[str, Any]]:
        """Collects maintenance node evidence using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        limit = int((os.getenv("HERON_DIAGNOSTICS_SAFE_EVIDENCE_NODES") or "25").strip() or "25")
        evidence: List[Dict[str, Any]] = []
        for node in nodes[: max(1, min(200, limit))]:
            name = str(node.get("name") or "").strip()
            if not name:
                continue
            qn = shlex.quote(name)
            commands = {
                "get_node_wide": self._inject_kubeconfig(f"kubectl get node {qn} -o wide", kubeconfig),
                "get_node_json": self._inject_kubeconfig(f"kubectl get node {qn} -o json", kubeconfig),
                "describe_node": self._inject_kubeconfig(f"kubectl describe node {qn}", kubeconfig),
                "pods_on_node": self._inject_kubeconfig(
                    f"kubectl get pods -A -o wide --field-selector spec.nodeName={qn}",
                    kubeconfig,
                ),
                "pods_on_node_non_running": self._inject_kubeconfig(
                    f"kubectl get pods -A -o wide --field-selector spec.nodeName={qn},status.phase!=Running",
                    kubeconfig,
                ),
                "events_signals": self._inject_kubeconfig(
                    f"kubectl get events -A --sort-by=.lastTimestamp | egrep '{qn}|maintenance|problem|detector|NPD|NodeProblemDetector|ReadOnly|readonly|mount|kernel|deadlock|corrupt|pressure|NotReady|Unhealthy|Evict|Failed|error|BackOff'",
                    kubeconfig,
                ),
            }
            if dry_run:
                evidence.append(
                    {
                        "name": name,
                        "reason": str(node.get("reason") or ""),
                        "status": "planned",
                        "commands": commands,
                    }
                )
                continue
            cmd_results: Dict[str, Any] = {}
            for key, command in commands.items():
                cmd_results[key] = self._run_shell(command, timeout_seconds=timeout_seconds)
            describe_stdout = str((cmd_results.get("describe_node") or {}).get("stdout") or "")
            events_stdout = str((cmd_results.get("events_signals") or {}).get("stdout") or "")
            evidence.append(
                {
                    "name": name,
                    "reason": str(node.get("reason") or ""),
                    "status": "collected",
                    "commands": commands,
                    "results": cmd_results,
                    "error_snippets": {
                        "describe": self._error_snippets(describe_stdout, max_lines=80),
                        "events": self._error_snippets(events_stdout, max_lines=80),
                    },
                }
            )
        return evidence

    def _collect_unhealthy_daemonsets(
        self,
        *,
        timeout_seconds: int,
        kubeconfig: str | None = None,
        target_namespace: str | None = None,
        target_name: str | None = None,
        target_namespaces_csv: str | None = None,
    ) -> Dict[str, Any]:
        """Collects unhealthy daemonsets using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        ns = str(target_namespace or "").strip()
        ds_name = str(target_name or "").strip()
        if ns and ds_name:
            return {
                "success": True,
                "daemonsets": [{"namespace": ns, "name": ds_name, "reason": "TARGETED"}],
                "source": "explicit_target",
            }

        cmd = self._inject_kubeconfig("kubectl get daemonsets -A -o json", kubeconfig)
        if not shutil.which("kubectl"):
            return {"success": False, "command": cmd, "error": "kubectl_not_found", "daemonsets": []}
        result = self._run_shell(cmd, timeout_seconds=timeout_seconds)
        if not result.get("success"):
            return {"success": False, "command": cmd, "error": result.get("stderr") or "kubectl_failed", "daemonsets": []}
        try:
            payload = json.loads(result.get("stdout") or "{}")
        except json.JSONDecodeError:
            return {"success": False, "command": cmd, "error": "invalid_json", "daemonsets": []}

        namespace_scope = self._parse_csv_set(target_namespaces_csv)
        daemonsets: List[Dict[str, Any]] = []
        items = payload.get("items") if isinstance(payload, dict) else []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            d_ns = str(metadata.get("namespace") or "").strip()
            d_name = str(metadata.get("name") or "").strip()
            if not d_ns or not d_name:
                continue
            if namespace_scope and d_ns not in namespace_scope:
                continue
            desired = int(status.get("desiredNumberScheduled") or 0)
            ready = int(status.get("numberReady") or 0)
            unavailable = int(status.get("numberUnavailable") or 0)
            if desired == ready and unavailable <= 0:
                continue
            daemonsets.append(
                {
                    "namespace": d_ns,
                    "name": d_name,
                    "desired": desired,
                    "ready": ready,
                    "unavailable": unavailable,
                    "reason": f"desired={desired},ready={ready},unavail={unavailable}",
                }
            )
        return {"success": True, "command": cmd, "daemonsets": daemonsets, "source": "auto_discovery"}

    def _collect_unhealthy_daemonset_pods(
        self,
        *,
        timeout_seconds: int,
        kubeconfig: str | None = None,
        daemonsets: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Collects unhealthy daemonset pods using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        pods: List[Dict[str, Any]] = []
        ds_evidence: List[Dict[str, Any]] = []
        for item in daemonsets:
            if not isinstance(item, dict):
                continue
            ns = str(item.get("namespace") or "").strip()
            ds = str(item.get("name") or "").strip()
            if not ns or not ds:
                continue
            q_ns = shlex.quote(ns)
            q_ds = shlex.quote(ds)
            ds_commands = {
                "get_daemonset_wide": self._inject_kubeconfig(f"kubectl get daemonset {q_ds} -n {q_ns} -o wide", kubeconfig),
                "describe_daemonset": self._inject_kubeconfig(f"kubectl describe daemonset {q_ds} -n {q_ns}", kubeconfig),
                "events_ns": self._inject_kubeconfig(
                    f"kubectl get events -n {q_ns} --sort-by=.lastTimestamp | tail -200",
                    kubeconfig,
                ),
                "daemonset_json": self._inject_kubeconfig(f"kubectl get daemonset {q_ds} -n {q_ns} -o json", kubeconfig),
                "pods_ns_json": self._inject_kubeconfig(f"kubectl get pods -n {q_ns} -o json", kubeconfig),
            }
            ds_results: Dict[str, Any] = {}
            for key, command in ds_commands.items():
                ds_results[key] = self._run_shell(command, timeout_seconds=timeout_seconds)
            ds_evidence.append({"namespace": ns, "name": ds, "commands": ds_commands, "results": ds_results})

            ds_json_raw = str((ds_results.get("daemonset_json") or {}).get("stdout") or "")
            pods_json_raw = str((ds_results.get("pods_ns_json") or {}).get("stdout") or "")
            try:
                ds_payload = json.loads(ds_json_raw or "{}")
                pods_payload = json.loads(pods_json_raw or "{}")
            except json.JSONDecodeError:
                continue
            selector_labels = (
                (ds_payload.get("spec") or {}).get("selector") or {}
            )
            selector_labels = selector_labels.get("matchLabels") if isinstance(selector_labels, dict) else {}
            selector_labels = selector_labels if isinstance(selector_labels, dict) else {}

            for pod_item in pods_payload.get("items", []) if isinstance(pods_payload, dict) else []:
                if not isinstance(pod_item, dict):
                    continue
                meta = pod_item.get("metadata") if isinstance(pod_item.get("metadata"), dict) else {}
                status = pod_item.get("status") if isinstance(pod_item.get("status"), dict) else {}
                spec = pod_item.get("spec") if isinstance(pod_item.get("spec"), dict) else {}
                pod_name = str(meta.get("name") or "").strip()
                if not pod_name:
                    continue
                labels = meta.get("labels") if isinstance(meta.get("labels"), dict) else {}
                owner_refs = meta.get("ownerReferences") if isinstance(meta.get("ownerReferences"), list) else []
                owner_match = any(
                    isinstance(ref, dict)
                    and str(ref.get("kind") or "") == "DaemonSet"
                    and str(ref.get("name") or "") == ds
                    for ref in owner_refs
                )
                label_match = bool(selector_labels) and all(str(labels.get(k) or "") == str(v) for k, v in selector_labels.items())
                if not owner_match and not label_match:
                    continue
                phase = str(status.get("phase") or "").strip()
                conditions = status.get("conditions") if isinstance(status.get("conditions"), list) else []
                ready = next(
                    (
                        str(cond.get("status") or "")
                        for cond in conditions
                        if isinstance(cond, dict) and str(cond.get("type") or "") == "Ready"
                    ),
                    "",
                )
                container_statuses = status.get("containerStatuses") if isinstance(status.get("containerStatuses"), list) else []
                waiting_reasons: List[str] = []
                for cst in container_statuses:
                    if not isinstance(cst, dict):
                        continue
                    waiting = (cst.get("state") or {}).get("waiting") if isinstance(cst.get("state"), dict) else {}
                    if isinstance(waiting, dict):
                        wr = str(waiting.get("reason") or "").strip()
                        if wr:
                            waiting_reasons.append(wr)
                if phase == "Running" and ready == "True":
                    continue
                pods.append(
                    {
                        "namespace": ns,
                        "name": pod_name,
                        "daemonset": ds,
                        "phase": phase,
                        "reason": str(status.get("reason") or "").strip(),
                        "node": str(spec.get("nodeName") or "").strip(),
                        "waiting_reason": ",".join(waiting_reasons[:3]),
                        "workload_hint": self._workload_hint(pod_name),
                    }
                )
        return {"success": True, "pods": pods, "daemonset_evidence": ds_evidence}

    def _collect_unhealthy_deployments(
        self,
        *,
        timeout_seconds: int,
        kubeconfig: str | None = None,
        target_namespace: str | None = None,
        target_name: str | None = None,
        target_namespaces_csv: str | None = None,
    ) -> Dict[str, Any]:
        """Collects unhealthy deployments using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        ns = str(target_namespace or "").strip()
        dep_name = str(target_name or "").strip()
        if ns and dep_name:
            return {
                "success": True,
                "deployments": [{"namespace": ns, "name": dep_name, "reason": "TARGETED"}],
                "source": "explicit_target",
            }

        cmd = self._inject_kubeconfig("kubectl get deployments -A -o json", kubeconfig)
        if not shutil.which("kubectl"):
            return {"success": False, "command": cmd, "error": "kubectl_not_found", "deployments": []}
        result = self._run_shell(cmd, timeout_seconds=timeout_seconds)
        if not result.get("success"):
            return {"success": False, "command": cmd, "error": result.get("stderr") or "kubectl_failed", "deployments": []}
        try:
            payload = json.loads(result.get("stdout") or "{}")
        except json.JSONDecodeError:
            return {"success": False, "command": cmd, "error": "invalid_json", "deployments": []}

        namespace_scope = self._parse_csv_set(target_namespaces_csv)
        deployments: List[Dict[str, Any]] = []
        items = payload.get("items") if isinstance(payload, dict) else []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            spec = item.get("spec") if isinstance(item.get("spec"), dict) else {}
            status = item.get("status") if isinstance(item.get("status"), dict) else {}
            d_ns = str(metadata.get("namespace") or "").strip()
            d_name = str(metadata.get("name") or "").strip()
            if not d_ns or not d_name:
                continue
            if namespace_scope and d_ns not in namespace_scope:
                continue
            desired = int(spec.get("replicas") if spec.get("replicas") is not None else 1)
            ready = int(status.get("readyReplicas") or 0)
            available = int(status.get("availableReplicas") or 0)
            if desired == ready and desired == available:
                continue
            deployments.append(
                {
                    "namespace": d_ns,
                    "name": d_name,
                    "desired": desired,
                    "ready": ready,
                    "available": available,
                    "reason": f"replicas={desired},ready={ready},available={available}",
                }
            )
        return {"success": True, "command": cmd, "deployments": deployments, "source": "auto_discovery"}

    def _collect_unhealthy_deployment_pods(
        self,
        *,
        timeout_seconds: int,
        kubeconfig: str | None = None,
        deployments: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Collects unhealthy deployment pods using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        pods: List[Dict[str, Any]] = []
        deploy_evidence: List[Dict[str, Any]] = []
        for item in deployments:
            if not isinstance(item, dict):
                continue
            ns = str(item.get("namespace") or "").strip()
            dep = str(item.get("name") or "").strip()
            if not ns or not dep:
                continue
            q_ns = shlex.quote(ns)
            q_dep = shlex.quote(dep)
            dep_commands = {
                "get_deployment_wide": self._inject_kubeconfig(f"kubectl get deployment {q_dep} -n {q_ns} -o wide", kubeconfig),
                "describe_deployment": self._inject_kubeconfig(f"kubectl describe deployment {q_dep} -n {q_ns}", kubeconfig),
                "replicasets_wide": self._inject_kubeconfig(f"kubectl get rs -n {q_ns} -o wide", kubeconfig),
                "events_ns": self._inject_kubeconfig(
                    f"kubectl get events -n {q_ns} --sort-by=.lastTimestamp | tail -200",
                    kubeconfig,
                ),
                "deployment_json": self._inject_kubeconfig(f"kubectl get deployment {q_dep} -n {q_ns} -o json", kubeconfig),
                "pods_ns_json": self._inject_kubeconfig(f"kubectl get pods -n {q_ns} -o json", kubeconfig),
            }
            dep_results: Dict[str, Any] = {}
            for key, command in dep_commands.items():
                dep_results[key] = self._run_shell(command, timeout_seconds=timeout_seconds)
            deploy_evidence.append({"namespace": ns, "name": dep, "commands": dep_commands, "results": dep_results})

            dep_json_raw = str((dep_results.get("deployment_json") or {}).get("stdout") or "")
            pods_json_raw = str((dep_results.get("pods_ns_json") or {}).get("stdout") or "")
            try:
                dep_payload = json.loads(dep_json_raw or "{}")
                pods_payload = json.loads(pods_json_raw or "{}")
            except json.JSONDecodeError:
                continue
            selector_labels = ((dep_payload.get("spec") or {}).get("selector") or {})
            selector_labels = selector_labels.get("matchLabels") if isinstance(selector_labels, dict) else {}
            selector_labels = selector_labels if isinstance(selector_labels, dict) else {}

            for pod_item in pods_payload.get("items", []) if isinstance(pods_payload, dict) else []:
                if not isinstance(pod_item, dict):
                    continue
                meta = pod_item.get("metadata") if isinstance(pod_item.get("metadata"), dict) else {}
                status = pod_item.get("status") if isinstance(pod_item.get("status"), dict) else {}
                spec = pod_item.get("spec") if isinstance(pod_item.get("spec"), dict) else {}
                pod_name = str(meta.get("name") or "").strip()
                if not pod_name:
                    continue
                labels = meta.get("labels") if isinstance(meta.get("labels"), dict) else {}
                label_match = bool(selector_labels) and all(str(labels.get(k) or "") == str(v) for k, v in selector_labels.items())
                if not label_match:
                    continue
                phase = str(status.get("phase") or "").strip()
                conditions = status.get("conditions") if isinstance(status.get("conditions"), list) else []
                ready = next(
                    (
                        str(cond.get("status") or "")
                        for cond in conditions
                        if isinstance(cond, dict) and str(cond.get("type") or "") == "Ready"
                    ),
                    "",
                )
                container_statuses = status.get("containerStatuses") if isinstance(status.get("containerStatuses"), list) else []
                waiting_reasons: List[str] = []
                for cst in container_statuses:
                    if not isinstance(cst, dict):
                        continue
                    waiting = (cst.get("state") or {}).get("waiting") if isinstance(cst.get("state"), dict) else {}
                    if isinstance(waiting, dict):
                        wr = str(waiting.get("reason") or "").strip()
                        if wr:
                            waiting_reasons.append(wr)
                if phase == "Running" and ready == "True":
                    continue
                pods.append(
                    {
                        "namespace": ns,
                        "name": pod_name,
                        "deployment": dep,
                        "phase": phase,
                        "reason": str(status.get("reason") or "").strip(),
                        "node": str(spec.get("nodeName") or "").strip(),
                        "waiting_reason": ",".join(waiting_reasons[:3]),
                        "workload_hint": self._workload_hint(pod_name),
                    }
                )
        return {"success": True, "pods": pods, "deployment_evidence": deploy_evidence}

    def _run_safe_pass(
        self,
        preview: Dict[str, Any],
        *,
        dry_run: bool,
        timeout_seconds: int,
        retries: int,
        kubeconfig: str | None = None,
        namespace_scope: str | None = None,
    ) -> Dict[str, Any]:
        """Runs safe pass using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        steps = preview.get("steps") if isinstance(preview.get("steps"), list) else []
        step_results: List[Dict[str, Any]] = []
        succeeded = 0
        failed = 0
        dependency_blocked = False

        for idx, raw_step in enumerate(steps, start=1):
            command = str(raw_step or "").strip()
            if not command:
                step_results.append({"index": idx, "status": "skipped", "reason": "empty_command", "command": ""})
                continue
            if dependency_blocked:
                failed += 1
                step_results.append(
                    {"index": idx, "status": "blocked", "reason": "prior_step_failed", "command": command}
                )
                continue
            command = self._inject_kubeconfig(command, kubeconfig)
            if not self._safe_command(command):
                failed += 1
                dependency_blocked = True
                step_results.append({"index": idx, "status": "blocked", "reason": "unsafe_command", "command": command})
                continue
            if dry_run:
                succeeded += 1
                step_results.append({"index": idx, "status": "planned", "reason": "dry_run", "command": command})
                continue

            attempts = 0
            result: Dict[str, Any] = {}
            for _ in range(max(0, retries) + 1):
                attempts += 1
                result = self._run_shell(command, timeout_seconds=timeout_seconds)
                if result.get("success"):
                    break
                if attempts <= max(0, retries):
                    time.sleep(min(3, attempts))
            if result.get("success"):
                succeeded += 1
                step_results.append({"index": idx, "status": "succeeded", "command": command, "attempts": attempts, **result})
            else:
                failed += 1
                dependency_blocked = True
                step_results.append({"index": idx, "status": "failed", "command": command, "attempts": attempts, **result})

        rid = str(preview.get("runbook_id") or "").strip().lower()
        unhealthy_snapshot = self._collect_unhealthy_pods(
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
            namespace_scope=namespace_scope,
        )
        safe_enrichment = k8s_strategies.collect_safe_enrichment(
            self,
            rid=rid,
            unhealthy_snapshot=unhealthy_snapshot,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
            namespace_scope=namespace_scope,
        )
        unhealthy_targets = safe_enrichment.get("unhealthy_targets", [])
        if not isinstance(unhealthy_targets, list):
            unhealthy_targets = []

        pod_down_selection = safe_enrichment.get("pod_down_selection", {})
        if not isinstance(pod_down_selection, dict):
            pod_down_selection = {"policy": "n/a", "targets": unhealthy_targets}

        quota_snapshot = safe_enrichment.get("quota_snapshot", {})
        if not isinstance(quota_snapshot, dict):
            quota_snapshot = {"success": True, "candidates": []}

        readonly_snapshot = safe_enrichment.get("readonly_snapshot", {})
        if not isinstance(readonly_snapshot, dict):
            readonly_snapshot = {"success": True, "nodes": []}
        readonly_evidence = safe_enrichment.get("readonly_evidence", [])
        if not isinstance(readonly_evidence, list):
            readonly_evidence = []

        maintenance_snapshot = safe_enrichment.get("maintenance_snapshot", {})
        if not isinstance(maintenance_snapshot, dict):
            maintenance_snapshot = {"success": True, "nodes": []}
        maintenance_evidence = safe_enrichment.get("maintenance_evidence", [])
        if not isinstance(maintenance_evidence, list):
            maintenance_evidence = []

        daemonset_snapshot = safe_enrichment.get("daemonset_snapshot", {})
        if not isinstance(daemonset_snapshot, dict):
            daemonset_snapshot = {"success": True, "daemonsets": []}
        daemonset_pods_snapshot = safe_enrichment.get("daemonset_pods_snapshot", {})
        if not isinstance(daemonset_pods_snapshot, dict):
            daemonset_pods_snapshot = {"success": True, "pods": [], "daemonset_evidence": []}

        deployment_snapshot = safe_enrichment.get("deployment_snapshot", {})
        if not isinstance(deployment_snapshot, dict):
            deployment_snapshot = {"success": True, "deployments": []}
        deployment_pods_snapshot = safe_enrichment.get("deployment_pods_snapshot", {})
        if not isinstance(deployment_pods_snapshot, dict):
            deployment_pods_snapshot = {"success": True, "pods": [], "deployment_evidence": []}

        pod_evidence = self._collect_pod_evidence(
            unhealthy_pods=unhealthy_targets,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
            namespace_scope=namespace_scope,
        )
        return {
            "pass": "safe",
            "steps": step_results,
            "steps_total": len(steps),
            "steps_succeeded": succeeded,
            "steps_failed": failed,
            "dependency_chain_satisfied": failed == 0,
            "unhealthy_pods": unhealthy_targets,
            "unhealthy_count": len(unhealthy_targets),
            "snapshot_error": unhealthy_snapshot.get("error"),
            "pod_evidence": pod_evidence,
            "pod_down_policy": pod_down_selection.get("policy"),
            "quota_candidates": quota_snapshot.get("candidates", []),
            "quota_candidates_count": len(quota_snapshot.get("candidates", [])),
            "quota_snapshot_error": quota_snapshot.get("error"),
            "readonly_nodes": readonly_snapshot.get("nodes", []),
            "readonly_nodes_count": len(readonly_snapshot.get("nodes", [])),
            "readonly_snapshot_error": readonly_snapshot.get("error"),
            "readonly_node_evidence": readonly_evidence,
            "maintenance_nodes": maintenance_snapshot.get("nodes", []),
            "maintenance_nodes_count": len(maintenance_snapshot.get("nodes", [])),
            "maintenance_snapshot_error": maintenance_snapshot.get("error"),
            "maintenance_node_evidence": maintenance_evidence,
            "daemonset_targets": daemonset_snapshot.get("daemonsets", []),
            "daemonset_targets_count": len(daemonset_snapshot.get("daemonsets", [])),
            "daemonset_snapshot_error": daemonset_snapshot.get("error"),
            "daemonset_unhealthy_pods_count": len(unhealthy_targets) if rid == "rbk-infrastructure-kubernetes-one-or-more-replica-unhealthy-in-daemonset" else 0,
            "daemonset_evidence": daemonset_pods_snapshot.get("daemonset_evidence", []),
            "deployment_targets": deployment_snapshot.get("deployments", []),
            "deployment_targets_count": len(deployment_snapshot.get("deployments", [])),
            "deployment_snapshot_error": deployment_snapshot.get("error"),
            "deployment_unhealthy_pods_count": len(unhealthy_targets) if rid == "rbk-infrastructure-kubernetes-one-or-more-replica-unhealthy" else 0,
            "deployment_evidence": deployment_pods_snapshot.get("deployment_evidence", []),
        }

    def _run_invasive_pass(
        self,
        *,
        dry_run: bool,
        timeout_seconds: int,
        preview: Dict[str, Any],
        unhealthy_pods: List[Dict[str, str]],
        quota_candidates: List[Dict[str, Any]] | None,
        readonly_nodes: List[Dict[str, Any]] | None,
        maintenance_nodes: List[Dict[str, Any]] | None,
        daemonset_targets: List[Dict[str, Any]] | None,
        deployment_targets: List[Dict[str, Any]] | None,
        invasive_enabled: bool,
        kubeconfig: str | None = None,
        namespace_scope: str | None = None,
    ) -> Dict[str, Any]:
        """Runs invasive pass using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if not invasive_enabled:
            return {"pass": "invasive", "status": "disabled", "actions": [], "deleted_count": 0}
        rid = str(preview.get("runbook_id") or "").strip().lower()
        k8s_result = k8s_strategies.run_invasive_strategy(
            self,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            rid=rid,
            unhealthy_pods=unhealthy_pods,
            quota_candidates=quota_candidates,
            readonly_nodes=readonly_nodes,
            maintenance_nodes=maintenance_nodes,
            daemonset_targets=daemonset_targets,
            deployment_targets=deployment_targets,
            kubeconfig=kubeconfig,
        )
        if isinstance(k8s_result, dict):
            return k8s_result

        actions: List[Dict[str, Any]] = []
        deleted = 0
        selected = self._select_invasive_targets(preview=preview, unhealthy_pods=unhealthy_pods)
        targets = selected.get("targets") if isinstance(selected.get("targets"), list) else []
        policy = str(selected.get("policy") or "all_unhealthy")
        if policy == "disabled":
            return {
                "pass": "invasive",
                "status": "disabled",
                "reason": "invasive_policy_disabled",
                "policy": policy,
                "actions": [],
                "deleted_count": 0,
            }
        max_pods = int((os.getenv("HERON_DIAGNOSTICS_MAX_INVASIVE_PODS") or "50").strip() or "50")
        namespace_filter = (namespace_scope or "").strip()
        for pod in targets[: max(1, min(200, max_pods))]:
            ns = str(pod.get("namespace") or "").strip()
            name = str(pod.get("name") or "").strip()
            if not ns or not name:
                continue
            if namespace_filter and ns != namespace_filter:
                continue
            command = self._inject_kubeconfig(f"kubectl delete pod -n {ns} {name} --wait=false", kubeconfig)
            if dry_run:
                actions.append({"namespace": ns, "name": name, "command": command, "status": "planned"})
                deleted += 1
                continue
            result = self._run_shell(command, timeout_seconds=timeout_seconds)
            status = "succeeded" if result.get("success") else "failed"
            if status == "succeeded":
                deleted += 1
            actions.append({"namespace": ns, "name": name, "command": command, "status": status, **result})
        return {"pass": "invasive", "status": "executed", "policy": policy, "actions": actions, "deleted_count": deleted}

    def _run_overwatch_pass(
        self,
        *,
        dry_run: bool,
        timeout_seconds: int,
        overwatch_seconds: int,
        poll_seconds: int,
        monitored_pods: List[Dict[str, str]],
        kubeconfig: str | None = None,
        namespace_scope: str | None = None,
    ) -> Dict[str, Any]:
        """Runs overwatch pass using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if dry_run:
            return {
                "pass": "overwatch",
                "status": "planned",
                "observations": [],
                "recovered_count": 0,
                "remaining_unhealthy_count": len(monitored_pods),
            }
        deadline = time.time() + max(10, overwatch_seconds)
        remaining = {
            (
                str(p.get("namespace") or ""),
                str(p.get("name") or ""),
                str(p.get("workload_hint") or self._workload_hint(str(p.get("name") or ""))),
            )
            for p in monitored_pods
            if p.get("namespace") and p.get("name")
        }
        observations: List[Dict[str, Any]] = []
        while time.time() < deadline and remaining:
            snapshot = self._collect_unhealthy_pods(
                timeout_seconds=timeout_seconds,
                kubeconfig=kubeconfig,
                namespace_scope=namespace_scope,
            )
            unhealthy_pairs = {
                (str(p.get("namespace") or ""), str(p.get("name") or ""))
                for p in snapshot.get("pods", [])
                if isinstance(p, dict)
            }
            unhealthy_hints = {
                (str(p.get("namespace") or ""), str(p.get("workload_hint") or self._workload_hint(str(p.get("name") or ""))))
                for p in snapshot.get("pods", [])
                if isinstance(p, dict)
            }
            recovered = [
                pair
                for pair in list(remaining)
                if (pair[0], pair[1]) not in unhealthy_pairs and (pair[0], pair[2]) not in unhealthy_hints
            ]
            for ns, name, hint in recovered:
                observations.append({"namespace": ns, "name": name, "status": "recovered"})
                remaining.discard((ns, name, hint))
            if remaining:
                time.sleep(max(1, poll_seconds))
        for ns, name, _ in sorted(remaining):
            observations.append({"namespace": ns, "name": name, "status": "still_unhealthy"})
        return {
            "pass": "overwatch",
            "status": "executed",
            "observations": observations,
            "recovered_count": sum(1 for item in observations if item.get("status") == "recovered"),
            "remaining_unhealthy_count": sum(1 for item in observations if item.get("status") == "still_unhealthy"),
        }

    def _run_quota_overwatch_pass(
        self,
        *,
        dry_run: bool,
        timeout_seconds: int,
        overwatch_seconds: int,
        poll_seconds: int,
        kubeconfig: str | None = None,
        namespace_scope: str | None = None,
        watch_namespaces: List[str] | None = None,
        threshold_percent: int = 95,
    ) -> Dict[str, Any]:
        """Runs quota overwatch using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        watch_set = {str(ns).strip() for ns in (watch_namespaces or []) if str(ns).strip()}
        if dry_run:
            return {
                "pass": "overwatch",
                "status": "planned",
                "observations": [],
                "recovered_count": 0,
                "remaining_unhealthy_count": len(watch_set),
            }
        deadline = time.time() + max(10, overwatch_seconds)
        last_high_ns: set[str] = set()
        while time.time() < deadline:
            snapshot = self._collect_quota_candidates(
                timeout_seconds=timeout_seconds,
                kubeconfig=kubeconfig,
                namespace_scope=namespace_scope,
                threshold_percent=threshold_percent,
                target_quota_name=str(os.getenv("HERON_QUOTA_TARGET_NAME") or "").strip() or None,
            )
            candidates = snapshot.get("candidates") if isinstance(snapshot.get("candidates"), list) else []
            high_ns = {
                str(item.get("namespace") or "").strip()
                for item in candidates
                if isinstance(item, dict) and item.get("namespace")
            }
            if watch_set:
                high_ns = {ns for ns in high_ns if ns in watch_set}
            last_high_ns = high_ns
            if not high_ns:
                observations = [
                    {"namespace": ns, "status": "quota_below_threshold"}
                    for ns in sorted(watch_set)
                ]
                return {
                    "pass": "overwatch",
                    "status": "executed",
                    "observations": observations,
                    "recovered_count": len(observations),
                    "remaining_unhealthy_count": 0,
                }
            time.sleep(max(1, poll_seconds))
        observations = [{"namespace": ns, "status": "quota_still_high"} for ns in sorted(last_high_ns)]
        return {
            "pass": "overwatch",
            "status": "executed",
            "observations": observations,
            "recovered_count": 0,
            "remaining_unhealthy_count": len(last_high_ns),
        }

    def _run_node_readonly_overwatch_pass(
        self,
        *,
        dry_run: bool,
        timeout_seconds: int,
        overwatch_seconds: int,
        poll_seconds: int,
        monitored_nodes: List[Dict[str, Any]],
        kubeconfig: str | None = None,
    ) -> Dict[str, Any]:
        """Runs node read-only overwatch using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        node_names = sorted(
            {
                str(item.get("name") or "").strip()
                for item in monitored_nodes
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            }
        )
        if dry_run:
            return {
                "pass": "overwatch",
                "status": "planned",
                "observations": [{"node": n, "status": "planned_check"} for n in node_names],
                "recovered_count": 0,
                "remaining_unhealthy_count": len(node_names),
            }
        deadline = time.time() + max(10, overwatch_seconds)
        last_bad: List[Dict[str, Any]] = []
        last_pending_count = 0
        while time.time() < deadline:
            nodes_cmd = self._inject_kubeconfig("kubectl get nodes -o json", kubeconfig)
            pending_cmd = self._inject_kubeconfig(
                "kubectl get pods -A --field-selector=status.phase=Pending -o json",
                kubeconfig,
            )
            nodes_res = self._run_shell(nodes_cmd, timeout_seconds=timeout_seconds)
            pending_res = self._run_shell(pending_cmd, timeout_seconds=timeout_seconds)
            if not nodes_res.get("success"):
                time.sleep(max(1, poll_seconds))
                continue
            try:
                nodes_payload = json.loads(nodes_res.get("stdout") or "{}")
            except json.JSONDecodeError:
                time.sleep(max(1, poll_seconds))
                continue
            try:
                pending_payload = json.loads(pending_res.get("stdout") or "{}") if pending_res.get("success") else {}
                items = pending_payload.get("items") if isinstance(pending_payload, dict) else []
                last_pending_count = len(items) if isinstance(items, list) else 0
            except json.JSONDecodeError:
                last_pending_count = 0

            node_map = {
                str(item.get("metadata", {}).get("name") or "").strip(): item
                for item in (nodes_payload.get("items") if isinstance(nodes_payload, dict) else [])
                if isinstance(item, dict)
            }
            bad: List[Dict[str, Any]] = []
            for node in node_names:
                raw = node_map.get(node) or {}
                status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
                conditions = status.get("conditions") if isinstance(status.get("conditions"), list) else []
                ro = "Unknown"
                ready = "Unknown"
                for cond in conditions:
                    if not isinstance(cond, dict):
                        continue
                    ctype = str(cond.get("type") or "")
                    cstatus = str(cond.get("status") or "Unknown")
                    if ctype == "NodePvcOrRootMountReadonly":
                        ro = cstatus
                    if ctype == "Ready":
                        ready = cstatus
                if ro == "True" or ready != "True":
                    bad.append({"node": node, "status": "still_bad", "readonly": ro, "ready": ready})
            last_bad = bad
            if not bad:
                return {
                    "pass": "overwatch",
                    "status": "executed",
                    "observations": [{"node": node, "status": "recovered"} for node in node_names],
                    "recovered_count": len(node_names),
                    "remaining_unhealthy_count": 0,
                    "pending_pods": last_pending_count,
                }
            time.sleep(max(1, poll_seconds))
        return {
            "pass": "overwatch",
            "status": "executed",
            "observations": last_bad,
            "recovered_count": 0,
            "remaining_unhealthy_count": len(last_bad),
            "pending_pods": last_pending_count,
        }

    def _run_node_maintenance_overwatch_pass(
        self,
        *,
        dry_run: bool,
        timeout_seconds: int,
        overwatch_seconds: int,
        poll_seconds: int,
        monitored_nodes: List[Dict[str, Any]],
        kubeconfig: str | None = None,
        condition_regex: str | None = None,
    ) -> Dict[str, Any]:
        """Runs node maintenance overwatch using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        node_names = sorted(
            {
                str(item.get("name") or "").strip()
                for item in monitored_nodes
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            }
        )
        if dry_run:
            return {
                "pass": "overwatch",
                "status": "planned",
                "observations": [{"node": n, "status": "planned_check"} for n in node_names],
                "recovered_count": 0,
                "remaining_unhealthy_count": len(node_names),
            }
        deadline = time.time() + max(10, overwatch_seconds)
        last_bad: List[Dict[str, Any]] = []
        last_pending_count = 0
        condition_re = str(condition_regex or "").strip()
        condition_pattern = re.compile(condition_re, re.IGNORECASE) if condition_re else None
        while time.time() < deadline:
            nodes_cmd = self._inject_kubeconfig("kubectl get nodes -o json", kubeconfig)
            pending_cmd = self._inject_kubeconfig(
                "kubectl get pods -A --field-selector=status.phase=Pending -o json",
                kubeconfig,
            )
            nodes_res = self._run_shell(nodes_cmd, timeout_seconds=timeout_seconds)
            pending_res = self._run_shell(pending_cmd, timeout_seconds=timeout_seconds)
            if not nodes_res.get("success"):
                time.sleep(max(1, poll_seconds))
                continue
            try:
                nodes_payload = json.loads(nodes_res.get("stdout") or "{}")
            except json.JSONDecodeError:
                time.sleep(max(1, poll_seconds))
                continue
            try:
                pending_payload = json.loads(pending_res.get("stdout") or "{}") if pending_res.get("success") else {}
                items = pending_payload.get("items") if isinstance(pending_payload, dict) else []
                last_pending_count = len(items) if isinstance(items, list) else 0
            except json.JSONDecodeError:
                last_pending_count = 0

            node_map = {
                str(item.get("metadata", {}).get("name") or "").strip(): item
                for item in (nodes_payload.get("items") if isinstance(nodes_payload, dict) else [])
                if isinstance(item, dict)
            }
            bad: List[Dict[str, Any]] = []
            for node in node_names:
                raw = node_map.get(node) or {}
                status = raw.get("status") if isinstance(raw.get("status"), dict) else {}
                conditions = status.get("conditions") if isinstance(status.get("conditions"), list) else []
                ready = "Unknown"
                bad_types: List[str] = []
                for cond in conditions:
                    if not isinstance(cond, dict):
                        continue
                    ctype = str(cond.get("type") or "")
                    cstatus = str(cond.get("status") or "Unknown")
                    if ctype == "Ready":
                        ready = cstatus
                        continue
                    if ctype == "NetworkUnavailable":
                        continue
                    if cstatus == "True":
                        bad_types.append(ctype)
                is_bad = False
                if condition_pattern:
                    regex_hit = any(condition_pattern.search(item) for item in bad_types)
                    is_bad = regex_hit or ready != "True"
                else:
                    is_bad = bool(bad_types) or ready != "True"
                if is_bad:
                    bad.append(
                        {
                            "node": node,
                            "status": "still_bad",
                            "ready": ready,
                            "bad_conditions": ",".join(sorted(set(bad_types))),
                        }
                    )
            last_bad = bad
            if not bad:
                return {
                    "pass": "overwatch",
                    "status": "executed",
                    "observations": [{"node": node, "status": "recovered"} for node in node_names],
                    "recovered_count": len(node_names),
                    "remaining_unhealthy_count": 0,
                    "pending_pods": last_pending_count,
                }
            time.sleep(max(1, poll_seconds))
        return {
            "pass": "overwatch",
            "status": "executed",
            "observations": last_bad,
            "recovered_count": 0,
            "remaining_unhealthy_count": len(last_bad),
            "pending_pods": last_pending_count,
        }

    def _run_daemonset_overwatch_pass(
        self,
        *,
        dry_run: bool,
        timeout_seconds: int,
        overwatch_seconds: int,
        poll_seconds: int,
        daemonsets: List[Dict[str, Any]],
        kubeconfig: str | None = None,
    ) -> Dict[str, Any]:
        """Runs daemonset overwatch using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        targets = [
            {"namespace": str(item.get("namespace") or "").strip(), "name": str(item.get("name") or "").strip()}
            for item in daemonsets
            if isinstance(item, dict) and str(item.get("namespace") or "").strip() and str(item.get("name") or "").strip()
        ]
        if dry_run:
            return {
                "pass": "overwatch",
                "status": "planned",
                "observations": [{"namespace": t["namespace"], "daemonset": t["name"], "status": "planned_check"} for t in targets],
                "recovered_count": 0,
                "remaining_unhealthy_count": len(targets),
            }
        deadline = time.time() + max(10, overwatch_seconds)
        last_bad: List[Dict[str, Any]] = []
        last_pending = 0
        while time.time() < deadline:
            pending_cmd = self._inject_kubeconfig("kubectl get pods -A --field-selector=status.phase=Pending -o json", kubeconfig)
            pending_res = self._run_shell(pending_cmd, timeout_seconds=timeout_seconds)
            if pending_res.get("success"):
                try:
                    pending_payload = json.loads(pending_res.get("stdout") or "{}")
                    p_items = pending_payload.get("items") if isinstance(pending_payload, dict) else []
                    last_pending = len(p_items) if isinstance(p_items, list) else 0
                except json.JSONDecodeError:
                    last_pending = 0
            bad: List[Dict[str, Any]] = []
            for ds in targets:
                ns = ds["namespace"]
                name = ds["name"]
                cmd = self._inject_kubeconfig(f"kubectl get daemonset {name} -n {ns} -o json", kubeconfig)
                result = self._run_shell(cmd, timeout_seconds=timeout_seconds)
                if not result.get("success"):
                    bad.append({"namespace": ns, "daemonset": name, "status": "unknown", "reason": "get_failed"})
                    continue
                try:
                    payload = json.loads(result.get("stdout") or "{}")
                except json.JSONDecodeError:
                    bad.append({"namespace": ns, "daemonset": name, "status": "unknown", "reason": "invalid_json"})
                    continue
                status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
                desired = int(status.get("desiredNumberScheduled") or 0)
                ready = int(status.get("numberReady") or 0)
                unavailable = int(status.get("numberUnavailable") or 0)
                if desired != ready or unavailable > 0:
                    bad.append(
                        {
                            "namespace": ns,
                            "daemonset": name,
                            "status": "still_unhealthy",
                            "desired": desired,
                            "ready": ready,
                            "unavailable": unavailable,
                        }
                    )
            last_bad = bad
            if not bad:
                return {
                    "pass": "overwatch",
                    "status": "executed",
                    "observations": [{"namespace": t["namespace"], "daemonset": t["name"], "status": "recovered"} for t in targets],
                    "recovered_count": len(targets),
                    "remaining_unhealthy_count": 0,
                    "pending_pods": last_pending,
                }
            time.sleep(max(1, poll_seconds))
        return {
            "pass": "overwatch",
            "status": "executed",
            "observations": last_bad,
            "recovered_count": 0,
            "remaining_unhealthy_count": len(last_bad),
            "pending_pods": last_pending,
        }

    def _run_deployment_overwatch_pass(
        self,
        *,
        dry_run: bool,
        timeout_seconds: int,
        overwatch_seconds: int,
        poll_seconds: int,
        deployments: List[Dict[str, Any]],
        kubeconfig: str | None = None,
    ) -> Dict[str, Any]:
        """Runs deployment overwatch using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        targets = [
            {"namespace": str(item.get("namespace") or "").strip(), "name": str(item.get("name") or "").strip()}
            for item in deployments
            if isinstance(item, dict) and str(item.get("namespace") or "").strip() and str(item.get("name") or "").strip()
        ]
        if dry_run:
            return {
                "pass": "overwatch",
                "status": "planned",
                "observations": [{"namespace": t["namespace"], "deployment": t["name"], "status": "planned_check"} for t in targets],
                "recovered_count": 0,
                "remaining_unhealthy_count": len(targets),
            }
        deadline = time.time() + max(10, overwatch_seconds)
        last_bad: List[Dict[str, Any]] = []
        last_pending = 0
        while time.time() < deadline:
            pending_cmd = self._inject_kubeconfig("kubectl get pods -A --field-selector=status.phase=Pending -o json", kubeconfig)
            pending_res = self._run_shell(pending_cmd, timeout_seconds=timeout_seconds)
            if pending_res.get("success"):
                try:
                    pending_payload = json.loads(pending_res.get("stdout") or "{}")
                    p_items = pending_payload.get("items") if isinstance(pending_payload, dict) else []
                    last_pending = len(p_items) if isinstance(p_items, list) else 0
                except json.JSONDecodeError:
                    last_pending = 0
            bad: List[Dict[str, Any]] = []
            for dep in targets:
                ns = dep["namespace"]
                name = dep["name"]
                cmd = self._inject_kubeconfig(f"kubectl get deployment {name} -n {ns} -o json", kubeconfig)
                result = self._run_shell(cmd, timeout_seconds=timeout_seconds)
                if not result.get("success"):
                    bad.append({"namespace": ns, "deployment": name, "status": "unknown", "reason": "get_failed"})
                    continue
                try:
                    payload = json.loads(result.get("stdout") or "{}")
                except json.JSONDecodeError:
                    bad.append({"namespace": ns, "deployment": name, "status": "unknown", "reason": "invalid_json"})
                    continue
                spec = payload.get("spec") if isinstance(payload.get("spec"), dict) else {}
                status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
                desired = int(spec.get("replicas") if spec.get("replicas") is not None else 1)
                ready = int(status.get("readyReplicas") or 0)
                available = int(status.get("availableReplicas") or 0)
                if desired != ready or desired != available:
                    bad.append(
                        {
                            "namespace": ns,
                            "deployment": name,
                            "status": "still_unhealthy",
                            "desired": desired,
                            "ready": ready,
                            "available": available,
                        }
                    )
            last_bad = bad
            if not bad:
                return {
                    "pass": "overwatch",
                    "status": "executed",
                    "observations": [{"namespace": t["namespace"], "deployment": t["name"], "status": "recovered"} for t in targets],
                    "recovered_count": len(targets),
                    "remaining_unhealthy_count": 0,
                    "pending_pods": last_pending,
                }
            time.sleep(max(1, poll_seconds))
        return {
            "pass": "overwatch",
            "status": "executed",
            "observations": last_bad,
            "recovered_count": 0,
            "remaining_unhealthy_count": len(last_bad),
            "pending_pods": last_pending,
        }

    def execute_workflow(
        self,
        *,
        preview: Dict[str, Any],
        dry_run: bool | None = None,
        timeout_seconds: int = 45,
        retries: int = 0,
        context: Dict[str, Any] | None = None,
        allow_invasive: bool = True,
    ) -> Dict[str, Any]:
        """Builds execute workflow using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        mode_dry_run = self._bool_env("HERON_DIAGNOSTICS_DRY_RUN", True) if dry_run is None else bool(dry_run)
        invasive_enabled = self._bool_env("HERON_DIAGNOSTICS_INVASIVE_ENABLED", False) and bool(allow_invasive)
        overwatch_seconds = int((os.getenv("HERON_DIAGNOSTICS_OVERWATCH_SECONDS") or "120").strip() or "120")
        poll_seconds = int((os.getenv("HERON_DIAGNOSTICS_OVERWATCH_POLL_SECONDS") or "10").strip() or "10")
        started_at = datetime.now(timezone.utc).isoformat()
        namespace_scope = str((context or {}).get("namespace") or "").strip() or None
        cluster_context = self._resolve_kubeconfig(context)
        if not cluster_context.get("resolved"):
            return {
                "status": "blocked",
                "execution_mode": "dry_run" if mode_dry_run else "execute",
                "started_at": started_at,
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "steps": [],
                "steps_total": 0,
                "steps_succeeded": 0,
                "steps_failed": 1,
                "safe_pass": {
                    "pass": "safe",
                    "steps": [],
                    "steps_total": 0,
                    "steps_succeeded": 0,
                    "steps_failed": 1,
                    "unhealthy_pods": [],
                    "unhealthy_count": 0,
                    "snapshot_error": str(cluster_context.get("reason") or "cluster_context_unresolved"),
                },
                "invasive_pass": {"pass": "invasive", "status": "blocked", "actions": [], "deleted_count": 0},
                "overwatch_pass": {
                    "pass": "overwatch",
                    "status": "blocked",
                    "observations": [],
                    "recovered_count": 0,
                    "remaining_unhealthy_count": 0,
                },
                "unhealthy_initial_count": 0,
                "unhealthy_final_count": 0,
                "recovered_count": 0,
                "cluster_context": cluster_context,
            }
        kubeconfig = cluster_context.get("kubeconfig")

        safe = self._run_safe_pass(
            preview,
            dry_run=mode_dry_run,
            timeout_seconds=timeout_seconds,
            retries=retries,
            kubeconfig=kubeconfig,
            namespace_scope=namespace_scope,
        )
        unhealthy = safe.get("unhealthy_pods") if isinstance(safe.get("unhealthy_pods"), list) else []
        safe_chain_ok = bool(safe.get("dependency_chain_satisfied"))
        if safe_chain_ok:
            invasive = self._run_invasive_pass(
                dry_run=mode_dry_run,
                timeout_seconds=timeout_seconds,
                preview=preview,
                unhealthy_pods=unhealthy,
                quota_candidates=safe.get("quota_candidates", []),
                readonly_nodes=safe.get("readonly_nodes", []),
                maintenance_nodes=safe.get("maintenance_nodes", []),
                daemonset_targets=safe.get("daemonset_targets", []),
                deployment_targets=safe.get("deployment_targets", []),
                invasive_enabled=invasive_enabled,
                kubeconfig=kubeconfig,
                namespace_scope=namespace_scope,
            )
        else:
            invasive = {
                "pass": "invasive",
                "status": "blocked",
                "reason": "safe_pass_incomplete",
                "actions": [],
                "deleted_count": 0,
            }
        monitored = unhealthy if not invasive.get("actions") else [
            {
                "namespace": item.get("namespace"),
                "name": item.get("name"),
                "workload_hint": self._workload_hint(str(item.get("name") or "")),
            }
            for item in invasive.get("actions", [])
            if isinstance(item, dict) and item.get("namespace") and item.get("name")
        ]
        runbook_id = str(preview.get("runbook_id") or "").strip().lower()
        overwatch = k8s_strategies.run_overwatch_strategy(
            self,
            runbook_id=runbook_id,
            dry_run=mode_dry_run,
            timeout_seconds=timeout_seconds,
            overwatch_seconds=overwatch_seconds,
            poll_seconds=poll_seconds,
            safe_pass=safe,
            kubeconfig=kubeconfig,
            namespace_scope=namespace_scope,
        )
        if not isinstance(overwatch, dict):
            overwatch = self._run_overwatch_pass(
                dry_run=mode_dry_run,
                timeout_seconds=timeout_seconds,
                overwatch_seconds=overwatch_seconds,
                poll_seconds=poll_seconds,
                monitored_pods=monitored,
                kubeconfig=kubeconfig,
                namespace_scope=namespace_scope,
            )

        status = "succeeded"
        if (overwatch.get("remaining_unhealthy_count") or 0) > 0:
            status = "failed"
        elif (safe.get("steps_failed") or 0) > 0:
            status = "partial"
        return {
            "status": status,
            "execution_mode": "dry_run" if mode_dry_run else "execute",
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            # Legacy flat fields retained for compatibility with existing tests/UI.
            "steps": safe.get("steps", []),
            "steps_total": int(safe.get("steps_total") or 0),
            "steps_succeeded": int(safe.get("steps_succeeded") or 0),
            "steps_failed": int(safe.get("steps_failed") or 0),
            "safe_pass": safe,
            "invasive_pass": invasive,
            "overwatch_pass": overwatch,
            "unhealthy_initial_count": len(unhealthy),
            "unhealthy_final_count": int(overwatch.get("remaining_unhealthy_count") or 0),
            "recovered_count": int(overwatch.get("recovered_count") or 0),
            "cluster_context": cluster_context,
        }

    def execute_preview(
        self,
        *,
        preview: Dict[str, Any],
        dry_run: bool | None = None,
        timeout_seconds: int = 45,
        retries: int = 0,
        context: Dict[str, Any] | None = None,
        allow_invasive: bool = True,
    ) -> Dict[str, Any]:
        """Builds execute preview using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        return self.execute_workflow(
            preview=preview,
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            retries=retries,
            context=context,
            allow_invasive=allow_invasive,
        )


diagnostics_runner = DiagnosticsRunner()
