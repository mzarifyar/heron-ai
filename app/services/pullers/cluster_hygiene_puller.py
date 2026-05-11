"""Cluster hygiene puller for periodic pod-state housekeeping checks.

"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import json
import os
import shutil
import subprocess

from ...core import get_logger
from ...integrations.kubernetes import get_kubeconfig_for_cluster, kubectl_json

logger = get_logger(__name__)

from app.core.paths import config as _cfg, data as _dat
DEFAULT_CLUSTER_TARGETS_PATH = _cfg("cluster_targets.json")


class ClusterHygienePuller:
    """Provides ClusterHygienePuller behavior using local state or integrations and exposes structured outputs for callers."""

    @staticmethod
    def _is_enabled(value: Any, default: bool = False) -> bool:
        """Checks enabled using local state or integration calls and returns a boolean flag (e.g., True), may raise ValueError for bad input while dependency errors may bubble."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return default

    @staticmethod
    def _to_iso_utc(value: Any) -> str:
        """Builds to iso utc using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        text = str(value or "").strip()
        if not text:
            return ""
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            else:
                parsed = parsed.astimezone(timezone.utc)
            return parsed.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except ValueError:
            return str(value or "")

    @staticmethod
    def _run_kubectl_text(kubeconfig: str, args: List[str], timeout: int = 60) -> Dict[str, Any]:
        """Runs kubectl text using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if not kubeconfig:
            return {"success": False, "stdout": "", "stderr": "missing kubeconfig", "code": -1}
        if not shutil.which("kubectl"):
            return {"success": False, "stdout": "", "stderr": "kubectl not found in PATH", "code": -1}
        cmd = ["kubectl", "--kubeconfig", kubeconfig] + args
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return {
                "success": proc.returncode == 0,
                "stdout": proc.stdout or "",
                "stderr": proc.stderr or "",
                "code": proc.returncode,
                "command": " ".join(cmd),
            }
        except Exception as exc:
            return {"success": False, "stdout": "", "stderr": str(exc), "code": -1, "command": " ".join(cmd)}

    @staticmethod
    def _count_kind(items: List[Dict[str, Any]], kind: str) -> int:
        """Builds count kind using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        total = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("kind") or "").strip().lower() == kind.lower():
                total += 1
        return total

    def _build_cleanup_command_previews(self, findings: List[Dict[str, Any]]) -> List[str]:
        """Builds cleanup command previews using local writes or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        previews: List[str] = []
        for item in findings:
            ns = str(item.get("namespace") or "").strip()
            pod = str(item.get("pod_name") or "").strip()
            if not ns or not pod:
                continue
            previews.append(f"kubectl delete pod -n {ns} {pod}")
        return previews[:100]

    def _load_targets(self) -> List[Dict[str, Any]]:
        """Loads targets using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        env_targets = (os.getenv("CORTEX_CLUSTER_TARGETS") or "").strip()
        if env_targets:
            payload = json.loads(env_targets)
        else:
            path = Path((os.getenv("CORTEX_CLUSTER_TARGETS_PATH") or DEFAULT_CLUSTER_TARGETS_PATH).strip())
            if not path.exists():
                return []
            payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return []
        targets = payload.get("targets")
        if not isinstance(targets, list):
            return []
        normalized: List[Dict[str, Any]] = []
        for item in targets:
            if not isinstance(item, dict):
                continue
            cluster = str(item.get("cluster") or item.get("cluster_name") or "").strip()
            if not cluster:
                continue
            normalized.append(
                {
                    "name": str(item.get("name") or cluster).strip() or cluster,
                    "cluster_name": cluster,
                    "account_id": str(item.get("account_id") or "").strip() or None,
                    "region": str(item.get("region") or "").strip() or "",
                    "environment": str(item.get("environment") or "prod").strip() or "prod",
                    "service": str(item.get("service") or "cluster-hygiene").strip() or "cluster-hygiene",
                    "tier": str(item.get("tier") or "platform").strip() or "platform",
                    "enabled": bool(item.get("enabled", True)),
                    "labels": item.get("labels") if isinstance(item.get("labels"), dict) else {},
                    "collect_details": self._is_enabled(item.get("collect_details"), default=True),
                    "collect_top_metrics": self._is_enabled(item.get("collect_top_metrics"), default=True),
                    "collect_events": self._is_enabled(item.get("collect_events"), default=True),
                    "events_tail_count": int(item.get("events_tail_count") or 100),
                    "cleanup_evicted_enabled": self._is_enabled(item.get("cleanup_evicted_enabled"), default=False),
                    "cleanup_completed_enabled": self._is_enabled(item.get("cleanup_completed_enabled"), default=False),
                    "cleanup_failed_enabled": self._is_enabled(item.get("cleanup_failed_enabled"), default=False),
                }
            )
        return [item for item in normalized if item.get("enabled", False)]

    @staticmethod
    def _pod_display_status(pod: Dict[str, Any]) -> Tuple[str, str, str]:
        """Builds pod display status using local reads or integration calls and returns a tuple result (e.g., ()), may raise ValueError for bad input while dependency errors may bubble."""
        status = pod.get("status") if isinstance(pod, dict) else {}
        if not isinstance(status, dict):
            return "Unknown", "Unknown", ""
        phase = str(status.get("phase") or "Unknown").strip() or "Unknown"
        reason = str(status.get("reason") or "").strip()
        container_statuses = status.get("containerStatuses") or []
        if isinstance(container_statuses, list):
            for container in container_statuses:
                if not isinstance(container, dict):
                    continue
                state = container.get("state")
                if not isinstance(state, dict):
                    continue
                waiting = state.get("waiting")
                if isinstance(waiting, dict):
                    waiting_reason = str(waiting.get("reason") or "").strip()
                    if waiting_reason:
                        return waiting_reason, phase, waiting_reason
                terminated = state.get("terminated")
                if isinstance(terminated, dict):
                    term_reason = str(terminated.get("reason") or "").strip()
                    if term_reason:
                        return term_reason, phase, term_reason
        if phase == "Succeeded":
            return "Completed", phase, reason
        return phase, phase, reason

    @staticmethod
    def _restart_count(pod: Dict[str, Any]) -> int:
        """Builds restart count using local reads or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
        status = pod.get("status") if isinstance(pod, dict) else {}
        if not isinstance(status, dict):
            return 0
        total = 0
        for item in status.get("containerStatuses") or []:
            if not isinstance(item, dict):
                continue
            try:
                total += int(item.get("restartCount") or 0)
            except (TypeError, ValueError):
                continue
        return total

    def run(
        self,
        *,
        range_hours: int,
        batch_size: int,
        cursor: Dict[str, Any] | None = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Runs the request using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        _ = range_hours, cursor
        targets = self._load_targets()
        now_utc = datetime.now(timezone.utc).replace(microsecond=0)
        if not targets:
            summary = {
                "targets_total": 0,
                "clusters_polled": 0,
                "clusters_with_findings": 0,
                "pods_total": 0,
                "findings_total": 0,
                "errors": [],
                "status": "no_targets_configured",
                "_findings": [],
            }
            return summary, {"last_run_utc": now_utc.isoformat().replace("+00:00", "Z")}

        findings: List[Dict[str, Any]] = []
        cluster_reports: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        clusters_polled = 0
        pods_total = 0
        clusters_with_findings = 0
        max_findings_per_cluster = max(20, int(batch_size))
        cleanup_actions_executed = 0
        cleanup_actions_failed = 0

        for target in targets:
            cluster_name = str(target.get("cluster_name") or "")
            try:
                kubeconfig = get_kubeconfig_for_cluster(
                    cluster_name,
                    account_id=target.get("account_id"),
                )
                if not kubeconfig:
                    raise RuntimeError(f"kubeconfig not found for cluster {cluster_name}")
                pods_obj, err = kubectl_json(kubeconfig, ["get", "pods", "-A"], timeout=90)
                if pods_obj is None:
                    raise RuntimeError(err or "failed to fetch pods")
                items = pods_obj.get("items") if isinstance(pods_obj, dict) else []
                if not isinstance(items, list):
                    items = []
                context_cmd = self._run_kubectl_text(kubeconfig, ["config", "current-context"], timeout=20)
                version_cmd = self._run_kubectl_text(kubeconfig, ["get", "--raw=/version"], timeout=20)
                cluster_info_cmd = self._run_kubectl_text(kubeconfig, ["cluster-info"], timeout=20)

                nodes_obj, nodes_err = kubectl_json(kubeconfig, ["get", "nodes"], timeout=60)
                ns_obj, ns_err = kubectl_json(kubeconfig, ["get", "ns"], timeout=60)
                workload_obj, workload_err = kubectl_json(
                    kubeconfig,
                    ["get", "deploy,sts,ds", "-A"],
                    timeout=90,
                )
                svc_obj, svc_err = kubectl_json(kubeconfig, ["get", "svc", "-A"], timeout=90)
                ep_obj, ep_err = kubectl_json(kubeconfig, ["get", "endpoints", "-A"], timeout=90)
                ing_obj, ing_err = kubectl_json(kubeconfig, ["get", "ingress", "-A"], timeout=90)
                pvc_obj, pvc_err = kubectl_json(kubeconfig, ["get", "pvc", "-A"], timeout=90)
                netpol_obj, netpol_err = kubectl_json(kubeconfig, ["get", "netpol", "-A"], timeout=90)
                events_obj, events_err = (None, "")
                if target.get("collect_events"):
                    events_obj, events_err = kubectl_json(kubeconfig, ["get", "events", "-A"], timeout=90)

                nodes_top_cmd: Dict[str, Any] | None = None
                pods_top_cmd: Dict[str, Any] | None = None
                if target.get("collect_top_metrics"):
                    nodes_top_cmd = self._run_kubectl_text(kubeconfig, ["top", "nodes"], timeout=30)
                    pods_top_cmd = self._run_kubectl_text(kubeconfig, ["top", "pods", "-A"], timeout=45)

                clusters_polled += 1
                pods_total += len(items)
                cluster_findings = 0
                cluster_findings_rows: List[Dict[str, Any]] = []
                for pod in items:
                    if not isinstance(pod, dict):
                        continue
                    display_status, phase, reason = self._pod_display_status(pod)
                    if display_status in {"Running", "Completed"}:
                        continue
                    meta = pod.get("metadata") if isinstance(pod.get("metadata"), dict) else {}
                    spec = pod.get("spec") if isinstance(pod.get("spec"), dict) else {}
                    findings.append(
                        {
                            "cluster_name": cluster_name,
                            "cluster_display_name": target.get("name") or cluster_name,
                            "namespace": str(meta.get("namespace") or ""),
                            "pod_name": str(meta.get("name") or ""),
                            "status": display_status,
                            "phase": phase,
                            "reason": reason,
                            "node_name": str(spec.get("nodeName") or ""),
                            "restart_count": self._restart_count(pod),
                            "created_at": self._to_iso_utc(meta.get("creationTimestamp")),
                        }
                    )
                    cluster_findings_rows.append(findings[-1])
                    cluster_findings += 1
                    if cluster_findings >= max_findings_per_cluster:
                        break
                if cluster_findings > 0:
                    clusters_with_findings += 1

                workloads = workload_obj.get("items") if isinstance(workload_obj, dict) else []
                if not isinstance(workloads, list):
                    workloads = []
                ns_items = ns_obj.get("items") if isinstance(ns_obj, dict) else []
                node_items = nodes_obj.get("items") if isinstance(nodes_obj, dict) else []
                svc_items = svc_obj.get("items") if isinstance(svc_obj, dict) else []
                ep_items = ep_obj.get("items") if isinstance(ep_obj, dict) else []
                ing_items = ing_obj.get("items") if isinstance(ing_obj, dict) else []
                pvc_items = pvc_obj.get("items") if isinstance(pvc_obj, dict) else []
                netpol_items = netpol_obj.get("items") if isinstance(netpol_obj, dict) else []
                events_items = events_obj.get("items") if isinstance(events_obj, dict) else []
                if not isinstance(events_items, list):
                    events_items = []
                events_tail = sorted(
                    [item for item in events_items if isinstance(item, dict)],
                    key=lambda item: (
                        str(item.get("lastTimestamp") or item.get("eventTime") or (item.get("metadata") or {}).get("creationTimestamp") or "")
                    ),
                )[-max(1, int(target.get("events_tail_count") or 100)) :]
                events_brief = [
                    {
                        "namespace": str((item.get("metadata") or {}).get("namespace") or ""),
                        "name": str((item.get("involvedObject") or {}).get("name") or ""),
                        "kind": str((item.get("involvedObject") or {}).get("kind") or ""),
                        "reason": str(item.get("reason") or ""),
                        "type": str(item.get("type") or ""),
                        "message": str(item.get("message") or "")[:240],
                        "timestamp": self._to_iso_utc(
                            item.get("lastTimestamp")
                            or item.get("eventTime")
                            or (item.get("metadata") or {}).get("creationTimestamp")
                        ),
                    }
                    for item in events_tail
                ]

                describe_samples: List[Dict[str, Any]] = []
                logs_samples: List[Dict[str, Any]] = []
                previous_logs_samples: List[Dict[str, Any]] = []
                if target.get("collect_details"):
                    for pod_item in cluster_findings_rows[:3]:
                        ns = str(pod_item.get("namespace") or "")
                        pod_name = str(pod_item.get("pod_name") or "")
                        if not ns or not pod_name:
                            continue
                        describe_result = self._run_kubectl_text(kubeconfig, ["describe", "pod", pod_name, "-n", ns], timeout=45)
                        logs_result = self._run_kubectl_text(kubeconfig, ["logs", pod_name, "-n", ns, "--tail=200"], timeout=45)
                        prev_logs_result = self._run_kubectl_text(
                            kubeconfig,
                            ["logs", pod_name, "-n", ns, "--previous", "--tail=200"],
                            timeout=45,
                        )
                        describe_samples.append(
                            {
                                "namespace": ns,
                                "pod": pod_name,
                                "success": bool(describe_result.get("success")),
                                "stderr": str(describe_result.get("stderr") or "")[:240],
                            }
                        )
                        logs_samples.append(
                            {
                                "namespace": ns,
                                "pod": pod_name,
                                "success": bool(logs_result.get("success")),
                                "stderr": str(logs_result.get("stderr") or "")[:240],
                            }
                        )
                        previous_logs_samples.append(
                            {
                                "namespace": ns,
                                "pod": pod_name,
                                "success": bool(prev_logs_result.get("success")),
                                "stderr": str(prev_logs_result.get("stderr") or "")[:240],
                            }
                        )

                cleanup_results: List[Dict[str, Any]] = []
                if target.get("cleanup_evicted_enabled"):
                    cmd = self._run_kubectl_text(
                        kubeconfig,
                        [
                            "get",
                            "pods",
                            "-A",
                            "--field-selector=status.phase=Failed",
                            "--no-headers",
                        ],
                        timeout=90,
                    )
                    if cmd.get("success"):
                        for line in str(cmd.get("stdout") or "").splitlines():
                            cols = line.split()
                            if len(cols) >= 4 and cols[3] == "Evicted":
                                delete = self._run_kubectl_text(kubeconfig, ["delete", "pod", "-n", cols[0], cols[1]], timeout=30)
                                cleanup_results.append(
                                    {
                                        "type": "evicted",
                                        "namespace": cols[0],
                                        "pod": cols[1],
                                        "success": bool(delete.get("success")),
                                    }
                                )
                                cleanup_actions_executed += 1
                                if not delete.get("success"):
                                    cleanup_actions_failed += 1
                if target.get("cleanup_completed_enabled"):
                    cmd = self._run_kubectl_text(
                        kubeconfig,
                        [
                            "get",
                            "pods",
                            "-A",
                            "--field-selector=status.phase=Succeeded",
                            "--no-headers",
                        ],
                        timeout=90,
                    )
                    if cmd.get("success"):
                        for line in str(cmd.get("stdout") or "").splitlines():
                            cols = line.split()
                            if len(cols) >= 2:
                                delete = self._run_kubectl_text(kubeconfig, ["delete", "pod", "-n", cols[0], cols[1]], timeout=30)
                                cleanup_results.append(
                                    {
                                        "type": "completed",
                                        "namespace": cols[0],
                                        "pod": cols[1],
                                        "success": bool(delete.get("success")),
                                    }
                                )
                                cleanup_actions_executed += 1
                                if not delete.get("success"):
                                    cleanup_actions_failed += 1
                if target.get("cleanup_failed_enabled"):
                    cmd = self._run_kubectl_text(
                        kubeconfig,
                        [
                            "get",
                            "pods",
                            "-A",
                            "--field-selector=status.phase=Failed",
                            "--no-headers",
                        ],
                        timeout=90,
                    )
                    if cmd.get("success"):
                        for line in str(cmd.get("stdout") or "").splitlines():
                            cols = line.split()
                            if len(cols) >= 2:
                                delete = self._run_kubectl_text(kubeconfig, ["delete", "pod", "-n", cols[0], cols[1]], timeout=30)
                                cleanup_results.append(
                                    {
                                        "type": "failed",
                                        "namespace": cols[0],
                                        "pod": cols[1],
                                        "success": bool(delete.get("success")),
                                    }
                                )
                                cleanup_actions_executed += 1
                                if not delete.get("success"):
                                    cleanup_actions_failed += 1

                preview_commands = self._build_cleanup_command_previews(cluster_findings_rows)
                cluster_reports.append(
                    {
                        "cluster_name": cluster_name,
                        "cluster_display_name": target.get("name") or cluster_name,
                        "context": {
                            "current_context": str(context_cmd.get("stdout") or "").strip(),
                            "api_version_check_ok": bool(version_cmd.get("success")),
                            "cluster_info_ok": bool(cluster_info_cmd.get("success")),
                        },
                        "inventory": {
                            "nodes": len(node_items),
                            "namespaces": len(ns_items),
                            "deployments": self._count_kind(workloads, "Deployment"),
                            "statefulsets": self._count_kind(workloads, "StatefulSet"),
                            "daemonsets": self._count_kind(workloads, "DaemonSet"),
                            "services": len(svc_items),
                            "endpoints": len(ep_items),
                            "ingresses": len(ing_items),
                            "pvcs": len(pvc_items),
                            "network_policies": len(netpol_items),
                            "pods_total": len(items),
                            "pods_not_running_or_completed": cluster_findings,
                        },
                        "metrics_top": {
                            "nodes_top_ok": bool(nodes_top_cmd.get("success")) if isinstance(nodes_top_cmd, dict) else False,
                            "pods_top_ok": bool(pods_top_cmd.get("success")) if isinstance(pods_top_cmd, dict) else False,
                        },
                        "events_tail": events_brief,
                        "pod_detail_samples": {
                            "describe": describe_samples,
                            "logs": logs_samples,
                            "logs_previous": previous_logs_samples,
                        },
                        "cleanup": {
                            "preview_delete_commands": preview_commands,
                            "actions": cleanup_results[:200],
                        },
                        "errors": [
                            item
                            for item in [
                                {"source": "nodes", "error": nodes_err} if nodes_err else None,
                                {"source": "namespaces", "error": ns_err} if ns_err else None,
                                {"source": "workloads", "error": workload_err} if workload_err else None,
                                {"source": "services", "error": svc_err} if svc_err else None,
                                {"source": "endpoints", "error": ep_err} if ep_err else None,
                                {"source": "ingress", "error": ing_err} if ing_err else None,
                                {"source": "pvc", "error": pvc_err} if pvc_err else None,
                                {"source": "netpol", "error": netpol_err} if netpol_err else None,
                                {"source": "events", "error": events_err} if events_err else None,
                            ]
                            if item is not None
                        ],
                    }
                )
            except Exception as exc:
                errors.append(
                    {
                        "cluster_name": cluster_name,
                        "region": target.get("region") or "",
                        "error": str(exc),
                        "source": "cluster_hygiene",
                    }
                )
                logger.warning("Cluster hygiene collection failed: %s", exc)

        summary = {
            "targets_total": len(targets),
            "clusters_polled": clusters_polled,
            "clusters_with_findings": clusters_with_findings,
            "pods_total": pods_total,
            "findings_total": len(findings),
            "cleanup_actions_executed": cleanup_actions_executed,
            "cleanup_actions_failed": cleanup_actions_failed,
            "cluster_reports": cluster_reports,
            "errors": errors,
            "_findings": findings,
        }
        return summary, {"last_run_utc": now_utc.isoformat().replace("+00:00", "Z")}