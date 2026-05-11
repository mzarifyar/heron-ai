"""Kubernetes diagnostics strategy handlers."""

from __future__ import annotations

from typing import Any, Dict, List
import json
import os
import shlex


def collect_safe_enrichment(
    runner: Any,
    *,
    rid: str,
    unhealthy_snapshot: Dict[str, Any],
    dry_run: bool,
    timeout_seconds: int,
    kubeconfig: str | None,
    namespace_scope: str | None,
) -> Dict[str, Any]:
    """Collects Kubernetes runbook-specific SAFE pass enrichment."""
    unhealthy_targets = unhealthy_snapshot.get("pods", []) if isinstance(unhealthy_snapshot.get("pods"), list) else []
    pod_down_selection: Dict[str, Any] = {"policy": "n/a", "targets": unhealthy_targets}
    if rid == "rbk-infrastructure-kubernetes-one-or-more-pod-is-down":
        pod_down_selection = runner._select_pod_down_targets(unhealthy_targets)
        unhealthy_targets = pod_down_selection.get("targets", []) if isinstance(pod_down_selection.get("targets"), list) else []

    daemonset_snapshot: Dict[str, Any] = {"success": True, "daemonsets": []}
    daemonset_pods_snapshot: Dict[str, Any] = {"success": True, "pods": [], "daemonset_evidence": []}
    if rid == "rbk-infrastructure-kubernetes-one-or-more-replica-unhealthy-in-daemonset":
        target_ns = str(os.getenv("CORTEX_DAEMONSET_TARGET_NAMESPACE") or "").strip() or None
        target_name = str(os.getenv("CORTEX_DAEMONSET_TARGET_NAME") or "").strip() or None
        target_ns_csv = str(os.getenv("CORTEX_DAEMONSET_TARGET_NAMESPACES_CSV") or "").strip() or None
        daemonset_snapshot = runner._collect_unhealthy_daemonsets(
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
            target_namespace=target_ns,
            target_name=target_name,
            target_namespaces_csv=target_ns_csv,
        )
        daemonset_pods_snapshot = runner._collect_unhealthy_daemonset_pods(
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
            daemonsets=daemonset_snapshot.get("daemonsets", []) if isinstance(daemonset_snapshot.get("daemonsets"), list) else [],
        )
        unhealthy_targets = daemonset_pods_snapshot.get("pods", []) if isinstance(daemonset_pods_snapshot.get("pods"), list) else []

    deployment_snapshot: Dict[str, Any] = {"success": True, "deployments": []}
    deployment_pods_snapshot: Dict[str, Any] = {"success": True, "pods": [], "deployment_evidence": []}
    if rid == "rbk-infrastructure-kubernetes-one-or-more-replica-unhealthy":
        target_ns = str(os.getenv("CORTEX_DEPLOYMENT_TARGET_NAMESPACE") or "").strip() or None
        target_name = str(os.getenv("CORTEX_DEPLOYMENT_TARGET_NAME") or "").strip() or None
        target_ns_csv = str(os.getenv("CORTEX_DEPLOYMENT_TARGET_NAMESPACES_CSV") or "").strip() or None
        deployment_snapshot = runner._collect_unhealthy_deployments(
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
            target_namespace=target_ns,
            target_name=target_name,
            target_namespaces_csv=target_ns_csv,
        )
        deployment_pods_snapshot = runner._collect_unhealthy_deployment_pods(
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
            deployments=deployment_snapshot.get("deployments", []) if isinstance(deployment_snapshot.get("deployments"), list) else [],
        )
        unhealthy_targets = deployment_pods_snapshot.get("pods", []) if isinstance(deployment_pods_snapshot.get("pods"), list) else []

    quota_snapshot: Dict[str, Any] = {"success": True, "candidates": []}
    if rid == "rbk-infrastructure-kubernetes-namesapce-quota-reached":
        threshold_percent = int((os.getenv("CORTEX_QUOTA_THRESHOLD_PERCENT") or "95").strip() or "95")
        target_quota_name = str(os.getenv("CORTEX_QUOTA_TARGET_NAME") or "").strip() or None
        quota_snapshot = runner._collect_quota_candidates(
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
            namespace_scope=namespace_scope,
            threshold_percent=threshold_percent,
            target_quota_name=target_quota_name,
        )

    readonly_snapshot: Dict[str, Any] = {"success": True, "nodes": []}
    readonly_evidence: List[Dict[str, Any]] = []
    if rid == "rbk-infrastructure-kubernetes-node-has-read-only-root-or-pvc-mount":
        node_selector = str(os.getenv("CORTEX_NODE_READONLY_SELECTOR") or "").strip() or None
        target_nodes_csv = str(os.getenv("CORTEX_NODE_READONLY_TARGET_NODES_CSV") or "").strip() or None
        readonly_snapshot = runner._collect_readonly_nodes(
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
            node_selector=node_selector,
            target_nodes_csv=target_nodes_csv,
        )
        readonly_evidence = runner._collect_node_readonly_evidence(
            nodes=readonly_snapshot.get("nodes", []) if isinstance(readonly_snapshot.get("nodes"), list) else [],
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
        )

    maintenance_snapshot: Dict[str, Any] = {"success": True, "nodes": []}
    maintenance_evidence: List[Dict[str, Any]] = []
    if rid == "rbk-infrastructure-kubernetes-one-or-more-nodes-need-maintenance":
        node_selector = str(os.getenv("CORTEX_NODE_MAINTENANCE_SELECTOR") or "").strip() or None
        target_nodes_csv = str(os.getenv("CORTEX_NODE_MAINTENANCE_TARGET_NODES_CSV") or "").strip() or None
        condition_regex = str(os.getenv("CORTEX_NODE_MAINTENANCE_CONDITION_REGEX") or "").strip() or None
        maintenance_snapshot = runner._collect_maintenance_nodes(
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
            node_selector=node_selector,
            target_nodes_csv=target_nodes_csv,
            condition_regex=condition_regex,
        )
        maintenance_evidence = runner._collect_node_maintenance_evidence(
            nodes=maintenance_snapshot.get("nodes", []) if isinstance(maintenance_snapshot.get("nodes"), list) else [],
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            kubeconfig=kubeconfig,
        )

    return {
        "unhealthy_targets": unhealthy_targets,
        "pod_down_selection": pod_down_selection,
        "quota_snapshot": quota_snapshot,
        "readonly_snapshot": readonly_snapshot,
        "readonly_evidence": readonly_evidence,
        "maintenance_snapshot": maintenance_snapshot,
        "maintenance_evidence": maintenance_evidence,
        "daemonset_snapshot": daemonset_snapshot,
        "daemonset_pods_snapshot": daemonset_pods_snapshot,
        "deployment_snapshot": deployment_snapshot,
        "deployment_pods_snapshot": deployment_pods_snapshot,
    }


def run_invasive_strategy(
    runner: Any,
    *,
    dry_run: bool,
    timeout_seconds: int,
    rid: str,
    unhealthy_pods: List[Dict[str, str]],
    quota_candidates: List[Dict[str, Any]] | None,
    readonly_nodes: List[Dict[str, Any]] | None,
    maintenance_nodes: List[Dict[str, Any]] | None,
    daemonset_targets: List[Dict[str, Any]] | None,
    deployment_targets: List[Dict[str, Any]] | None,
    kubeconfig: str | None,
) -> Dict[str, Any] | None:
    """Executes Kubernetes runbook-specific INVASIVE logic."""
    if rid == "rbk-infrastructure-kubernetes-namesapce-quota-reached":
        quota_patch_enabled = runner._bool_env("CORTEX_QUOTA_PATCH_ENABLED", False)
        if not quota_patch_enabled:
            return {
                "pass": "invasive",
                "status": "disabled",
                "reason": "quota_patch_disabled",
                "policy": "quota_patch_pods_hard",
                "actions": [],
                "deleted_count": 0,
            }
        explicit_new = str(os.getenv("CORTEX_QUOTA_NEW_PODS_HARD") or "").strip()
        increase_by = str(os.getenv("CORTEX_QUOTA_INCREASE_PODS_BY") or "").strip()
        if not explicit_new and not increase_by:
            return {
                "pass": "invasive",
                "status": "blocked",
                "reason": "quota_patch_value_missing",
                "policy": "quota_patch_pods_hard",
                "actions": [],
                "deleted_count": 0,
            }
        actions: List[Dict[str, Any]] = []
        patched = 0
        targets = quota_candidates if isinstance(quota_candidates, list) else []
        for quota in targets:
            if not isinstance(quota, dict):
                continue
            ns = str(quota.get("namespace") or "").strip()
            rq = str(quota.get("quota_name") or "").strip()
            old_hard = int(quota.get("hard_pods") or 0)
            if not ns or not rq or old_hard <= 0:
                continue
            if explicit_new:
                if not explicit_new.isdigit():
                    actions.append(
                        {
                            "namespace": ns,
                            "quota_name": rq,
                            "status": "failed",
                            "reason": "invalid_new_hard_value",
                            "old_hard": old_hard,
                        }
                    )
                    continue
                new_hard = int(explicit_new)
            else:
                if not increase_by.isdigit():
                    actions.append(
                        {
                            "namespace": ns,
                            "quota_name": rq,
                            "status": "failed",
                            "reason": "invalid_increase_value",
                            "old_hard": old_hard,
                        }
                    )
                    continue
                new_hard = old_hard + int(increase_by)
            payload = json.dumps({"spec": {"hard": {"pods": str(new_hard)}}}, separators=(",", ":"))
            command = runner._inject_kubeconfig(
                f"kubectl patch resourcequota {shlex.quote(rq)} -n {shlex.quote(ns)} --type=merge -p {shlex.quote(payload)}",
                kubeconfig,
            )
            if dry_run:
                actions.append(
                    {
                        "namespace": ns,
                        "quota_name": rq,
                        "old_hard": old_hard,
                        "new_hard": new_hard,
                        "command": command,
                        "status": "planned",
                    }
                )
                patched += 1
                continue
            result = runner._run_shell(command, timeout_seconds=timeout_seconds)
            status = "succeeded" if result.get("success") else "failed"
            if status == "succeeded":
                patched += 1
            actions.append(
                {
                    "namespace": ns,
                    "quota_name": rq,
                    "old_hard": old_hard,
                    "new_hard": new_hard,
                    "command": command,
                    "status": status,
                    **result,
                }
            )
        return {
            "pass": "invasive",
            "status": "executed",
            "policy": "quota_patch_pods_hard",
            "actions": actions,
            "deleted_count": patched,
            "patched_count": patched,
        }

    if rid == "rbk-infrastructure-kubernetes-node-has-read-only-root-or-pvc-mount":
        do_cordon = runner._bool_env("CORTEX_NODE_READONLY_DO_CORDON", False)
        do_drain = runner._bool_env("CORTEX_NODE_READONLY_DO_DRAIN", False)
        if not do_cordon and not do_drain:
            return {
                "pass": "invasive",
                "status": "disabled",
                "reason": "node_readonly_actions_disabled",
                "policy": "node_cordon_drain",
                "actions": [],
                "deleted_count": 0,
            }
        drain_timeout = str(os.getenv("CORTEX_NODE_READONLY_DRAIN_TIMEOUT") or "10m").strip() or "10m"
        drain_ignore_ds = runner._bool_env("CORTEX_NODE_READONLY_DRAIN_IGNORE_DAEMONSETS", True)
        drain_delete_emptydir = runner._bool_env("CORTEX_NODE_READONLY_DRAIN_DELETE_EMPTYDIR", False)
        drain_force = runner._bool_env("CORTEX_NODE_READONLY_DRAIN_FORCE", False)
        targets = readonly_nodes if isinstance(readonly_nodes, list) else []
        actions: List[Dict[str, Any]] = []
        action_count = 0
        for item in targets:
            if not isinstance(item, dict):
                continue
            node = str(item.get("name") or "").strip()
            if not node:
                continue
            qn = shlex.quote(node)
            if do_cordon:
                cordon_cmd = runner._inject_kubeconfig(f"kubectl cordon {qn}", kubeconfig)
                if dry_run:
                    actions.append({"node": node, "operation": "cordon", "command": cordon_cmd, "status": "planned"})
                    action_count += 1
                else:
                    res = runner._run_shell(cordon_cmd, timeout_seconds=timeout_seconds)
                    status = "succeeded" if res.get("success") else "failed"
                    if status == "succeeded":
                        action_count += 1
                    actions.append({"node": node, "operation": "cordon", "command": cordon_cmd, "status": status, **res})
            if do_drain:
                drain_parts = [f"kubectl drain {qn} --timeout={shlex.quote(drain_timeout)}"]
                if drain_ignore_ds:
                    drain_parts.append("--ignore-daemonsets")
                if drain_delete_emptydir:
                    drain_parts.append("--delete-emptydir-data")
                if drain_force:
                    drain_parts.append("--force")
                drain_cmd = runner._inject_kubeconfig(" ".join(drain_parts), kubeconfig)
                if dry_run:
                    actions.append({"node": node, "operation": "drain", "command": drain_cmd, "status": "planned"})
                    action_count += 1
                else:
                    res = runner._run_shell(drain_cmd, timeout_seconds=max(timeout_seconds, 120))
                    status = "succeeded" if res.get("success") else "failed"
                    if status == "succeeded":
                        action_count += 1
                    actions.append({"node": node, "operation": "drain", "command": drain_cmd, "status": status, **res})
        return {
            "pass": "invasive",
            "status": "executed",
            "policy": "node_cordon_drain",
            "actions": actions,
            "deleted_count": action_count,
            "node_action_count": action_count,
        }

    if rid == "rbk-infrastructure-kubernetes-one-or-more-pod-is-down":
        do_restart = runner._bool_env("CORTEX_POD_DOWN_DO_RESTART_PODS", True)
        if not do_restart:
            return {
                "pass": "invasive",
                "status": "disabled",
                "reason": "pod_restart_disabled",
                "policy": "pod_delete_restart",
                "actions": [],
                "deleted_count": 0,
            }
        actions: List[Dict[str, Any]] = []
        deleted = 0
        max_pods = int((os.getenv("CORTEX_DIAGNOSTICS_MAX_INVASIVE_PODS") or "50").strip() or "50")
        for pod in unhealthy_pods[: max(1, min(200, max_pods))]:
            ns = str(pod.get("namespace") or "").strip()
            name = str(pod.get("name") or "").strip()
            if not ns or not name:
                continue
            command = runner._inject_kubeconfig(f"kubectl delete pod -n {ns} {name} --wait=false", kubeconfig)
            if dry_run:
                actions.append({"namespace": ns, "name": name, "command": command, "status": "planned"})
                deleted += 1
                continue
            result = runner._run_shell(command, timeout_seconds=timeout_seconds)
            status = "succeeded" if result.get("success") else "failed"
            if status == "succeeded":
                deleted += 1
            actions.append({"namespace": ns, "name": name, "command": command, "status": status, **result})
        return {
            "pass": "invasive",
            "status": "executed",
            "policy": "pod_delete_restart",
            "actions": actions,
            "deleted_count": deleted,
        }

    if rid == "rbk-infrastructure-kubernetes-one-or-more-replica-unhealthy-in-daemonset":
        do_restart_pods = runner._bool_env("CORTEX_DAEMONSET_DO_RESTART_UNHEALTHY_PODS", True)
        do_rollout_restart = runner._bool_env("CORTEX_DAEMONSET_DO_ROLLOUT_RESTART", False)
        if not do_restart_pods and not do_rollout_restart:
            return {
                "pass": "invasive",
                "status": "disabled",
                "reason": "daemonset_actions_disabled",
                "policy": "daemonset_pod_restart_and_optional_rollout",
                "actions": [],
                "deleted_count": 0,
            }
        actions: List[Dict[str, Any]] = []
        deleted = 0
        rollout_count = 0
        max_pods = int((os.getenv("CORTEX_DIAGNOSTICS_MAX_INVASIVE_PODS") or "50").strip() or "50")
        if do_restart_pods:
            for pod in unhealthy_pods[: max(1, min(200, max_pods))]:
                ns = str(pod.get("namespace") or "").strip()
                name = str(pod.get("name") or "").strip()
                ds_name = str(pod.get("daemonset") or "").strip()
                if not ns or not name:
                    continue
                command = runner._inject_kubeconfig(f"kubectl delete pod -n {ns} {name} --wait=false", kubeconfig)
                if dry_run:
                    actions.append(
                        {"namespace": ns, "name": name, "daemonset": ds_name, "operation": "delete_pod", "command": command, "status": "planned"}
                    )
                    deleted += 1
                    continue
                result = runner._run_shell(command, timeout_seconds=timeout_seconds)
                status = "succeeded" if result.get("success") else "failed"
                if status == "succeeded":
                    deleted += 1
                actions.append(
                    {"namespace": ns, "name": name, "daemonset": ds_name, "operation": "delete_pod", "command": command, "status": status, **result}
                )
        if do_rollout_restart:
            for ds in daemonset_targets if isinstance(daemonset_targets, list) else []:
                if not isinstance(ds, dict):
                    continue
                ns = str(ds.get("namespace") or "").strip()
                ds_name = str(ds.get("name") or "").strip()
                if not ns or not ds_name:
                    continue
                command = runner._inject_kubeconfig(f"kubectl rollout restart daemonset {ds_name} -n {ns}", kubeconfig)
                if dry_run:
                    actions.append(
                        {"namespace": ns, "daemonset": ds_name, "operation": "rollout_restart", "command": command, "status": "planned"}
                    )
                    rollout_count += 1
                    continue
                result = runner._run_shell(command, timeout_seconds=timeout_seconds)
                status = "succeeded" if result.get("success") else "failed"
                if status == "succeeded":
                    rollout_count += 1
                actions.append(
                    {"namespace": ns, "daemonset": ds_name, "operation": "rollout_restart", "command": command, "status": status, **result}
                )
        return {
            "pass": "invasive",
            "status": "executed",
            "policy": "daemonset_pod_restart_and_optional_rollout",
            "actions": actions,
            "deleted_count": deleted,
            "rollout_restart_count": rollout_count,
        }

    if rid == "rbk-infrastructure-kubernetes-one-or-more-replica-unhealthy":
        do_restart_pods = runner._bool_env("CORTEX_DEPLOYMENT_DO_RESTART_UNHEALTHY_PODS", True)
        do_rollout_restart = runner._bool_env("CORTEX_DEPLOYMENT_DO_ROLLOUT_RESTART", False)
        if not do_restart_pods and not do_rollout_restart:
            return {
                "pass": "invasive",
                "status": "disabled",
                "reason": "deployment_actions_disabled",
                "policy": "deployment_pod_restart_and_optional_rollout",
                "actions": [],
                "deleted_count": 0,
            }
        actions: List[Dict[str, Any]] = []
        deleted = 0
        rollout_count = 0
        max_pods = int((os.getenv("CORTEX_DIAGNOSTICS_MAX_INVASIVE_PODS") or "50").strip() or "50")
        if do_restart_pods:
            for pod in unhealthy_pods[: max(1, min(200, max_pods))]:
                ns = str(pod.get("namespace") or "").strip()
                name = str(pod.get("name") or "").strip()
                dep_name = str(pod.get("deployment") or "").strip()
                if not ns or not name:
                    continue
                command = runner._inject_kubeconfig(f"kubectl delete pod -n {ns} {name} --wait=false", kubeconfig)
                if dry_run:
                    actions.append(
                        {"namespace": ns, "name": name, "deployment": dep_name, "operation": "delete_pod", "command": command, "status": "planned"}
                    )
                    deleted += 1
                    continue
                result = runner._run_shell(command, timeout_seconds=timeout_seconds)
                status = "succeeded" if result.get("success") else "failed"
                if status == "succeeded":
                    deleted += 1
                actions.append(
                    {"namespace": ns, "name": name, "deployment": dep_name, "operation": "delete_pod", "command": command, "status": status, **result}
                )
        if do_rollout_restart:
            for dep in deployment_targets if isinstance(deployment_targets, list) else []:
                if not isinstance(dep, dict):
                    continue
                ns = str(dep.get("namespace") or "").strip()
                dep_name = str(dep.get("name") or "").strip()
                if not ns or not dep_name:
                    continue
                command = runner._inject_kubeconfig(f"kubectl rollout restart deployment {dep_name} -n {ns}", kubeconfig)
                if dry_run:
                    actions.append(
                        {"namespace": ns, "deployment": dep_name, "operation": "rollout_restart", "command": command, "status": "planned"}
                    )
                    rollout_count += 1
                    continue
                result = runner._run_shell(command, timeout_seconds=timeout_seconds)
                status = "succeeded" if result.get("success") else "failed"
                if status == "succeeded":
                    rollout_count += 1
                actions.append(
                    {"namespace": ns, "deployment": dep_name, "operation": "rollout_restart", "command": command, "status": status, **result}
                )
        return {
            "pass": "invasive",
            "status": "executed",
            "policy": "deployment_pod_restart_and_optional_rollout",
            "actions": actions,
            "deleted_count": deleted,
            "rollout_restart_count": rollout_count,
        }

    if rid == "rbk-infrastructure-kubernetes-one-or-more-nodes-need-maintenance":
        do_cordon = runner._bool_env("CORTEX_NODE_MAINTENANCE_DO_CORDON", False)
        do_drain = runner._bool_env("CORTEX_NODE_MAINTENANCE_DO_DRAIN", False)
        if not do_cordon and not do_drain:
            return {
                "pass": "invasive",
                "status": "disabled",
                "reason": "node_maintenance_actions_disabled",
                "policy": "node_maintenance_cordon_drain",
                "actions": [],
                "deleted_count": 0,
            }
        drain_timeout = str(os.getenv("CORTEX_NODE_MAINTENANCE_DRAIN_TIMEOUT") or "10m").strip() or "10m"
        drain_ignore_ds = runner._bool_env("CORTEX_NODE_MAINTENANCE_DRAIN_IGNORE_DAEMONSETS", True)
        drain_delete_emptydir = runner._bool_env("CORTEX_NODE_MAINTENANCE_DRAIN_DELETE_EMPTYDIR", False)
        drain_force = runner._bool_env("CORTEX_NODE_MAINTENANCE_DRAIN_FORCE", False)
        targets = maintenance_nodes if isinstance(maintenance_nodes, list) else []
        actions: List[Dict[str, Any]] = []
        action_count = 0
        for item in targets:
            if not isinstance(item, dict):
                continue
            node = str(item.get("name") or "").strip()
            if not node:
                continue
            qn = shlex.quote(node)
            if do_cordon:
                cordon_cmd = runner._inject_kubeconfig(f"kubectl cordon {qn}", kubeconfig)
                if dry_run:
                    actions.append({"node": node, "operation": "cordon", "command": cordon_cmd, "status": "planned"})
                    action_count += 1
                else:
                    res = runner._run_shell(cordon_cmd, timeout_seconds=timeout_seconds)
                    status = "succeeded" if res.get("success") else "failed"
                    if status == "succeeded":
                        action_count += 1
                    actions.append({"node": node, "operation": "cordon", "command": cordon_cmd, "status": status, **res})
            if do_drain:
                drain_parts = [f"kubectl drain {qn} --timeout={shlex.quote(drain_timeout)}"]
                if drain_ignore_ds:
                    drain_parts.append("--ignore-daemonsets")
                if drain_delete_emptydir:
                    drain_parts.append("--delete-emptydir-data")
                if drain_force:
                    drain_parts.append("--force")
                drain_cmd = runner._inject_kubeconfig(" ".join(drain_parts), kubeconfig)
                if dry_run:
                    actions.append({"node": node, "operation": "drain", "command": drain_cmd, "status": "planned"})
                    action_count += 1
                else:
                    res = runner._run_shell(drain_cmd, timeout_seconds=max(timeout_seconds, 120))
                    status = "succeeded" if res.get("success") else "failed"
                    if status == "succeeded":
                        action_count += 1
                    actions.append({"node": node, "operation": "drain", "command": drain_cmd, "status": status, **res})
        return {
            "pass": "invasive",
            "status": "executed",
            "policy": "node_maintenance_cordon_drain",
            "actions": actions,
            "deleted_count": action_count,
            "node_action_count": action_count,
        }

    return None


def run_overwatch_strategy(
    runner: Any,
    *,
    runbook_id: str,
    dry_run: bool,
    timeout_seconds: int,
    overwatch_seconds: int,
    poll_seconds: int,
    safe_pass: Dict[str, Any],
    kubeconfig: str | None,
    namespace_scope: str | None,
) -> Dict[str, Any] | None:
    """Executes Kubernetes runbook-specific OVERWATCH logic."""
    if runbook_id == "rbk-infrastructure-kubernetes-namesapce-quota-reached":
        threshold_percent = int((os.getenv("CORTEX_QUOTA_THRESHOLD_PERCENT") or "95").strip() or "95")
        quota_candidates = safe_pass.get("quota_candidates", []) if isinstance(safe_pass.get("quota_candidates"), list) else []
        watch_namespaces = sorted(
            {
                str(item.get("namespace") or "").strip()
                for item in quota_candidates
                if isinstance(item, dict) and item.get("namespace")
            }
        )
        return runner._run_quota_overwatch_pass(
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            overwatch_seconds=overwatch_seconds,
            poll_seconds=poll_seconds,
            kubeconfig=kubeconfig,
            namespace_scope=namespace_scope,
            watch_namespaces=watch_namespaces,
            threshold_percent=threshold_percent,
        )

    if runbook_id == "rbk-infrastructure-kubernetes-node-has-read-only-root-or-pvc-mount":
        return runner._run_node_readonly_overwatch_pass(
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            overwatch_seconds=overwatch_seconds,
            poll_seconds=poll_seconds,
            monitored_nodes=safe_pass.get("readonly_nodes", []) if isinstance(safe_pass.get("readonly_nodes"), list) else [],
            kubeconfig=kubeconfig,
        )

    if runbook_id == "rbk-infrastructure-kubernetes-one-or-more-nodes-need-maintenance":
        condition_regex = str(os.getenv("CORTEX_NODE_MAINTENANCE_CONDITION_REGEX") or "").strip() or None
        return runner._run_node_maintenance_overwatch_pass(
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            overwatch_seconds=overwatch_seconds,
            poll_seconds=poll_seconds,
            monitored_nodes=safe_pass.get("maintenance_nodes", []) if isinstance(safe_pass.get("maintenance_nodes"), list) else [],
            kubeconfig=kubeconfig,
            condition_regex=condition_regex,
        )

    if runbook_id == "rbk-infrastructure-kubernetes-one-or-more-replica-unhealthy-in-daemonset":
        return runner._run_daemonset_overwatch_pass(
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            overwatch_seconds=overwatch_seconds,
            poll_seconds=poll_seconds,
            daemonsets=safe_pass.get("daemonset_targets", []) if isinstance(safe_pass.get("daemonset_targets"), list) else [],
            kubeconfig=kubeconfig,
        )

    if runbook_id == "rbk-infrastructure-kubernetes-one-or-more-replica-unhealthy":
        return runner._run_deployment_overwatch_pass(
            dry_run=dry_run,
            timeout_seconds=timeout_seconds,
            overwatch_seconds=overwatch_seconds,
            poll_seconds=poll_seconds,
            deployments=safe_pass.get("deployment_targets", []) if isinstance(safe_pass.get("deployment_targets"), list) else [],
            kubeconfig=kubeconfig,
        )

    return None

