"""

"""

from typing import Any, Dict, List, Optional, Tuple
import os
import json
import shutil
import subprocess
from pathlib import Path
from utils.logger import log

__all__ = [
    "get_kubeconfig_for_cluster",
    "get_active_clusters_by_account_id",
    "kubectl_json",
    "check_deployment_health",
    "rollout_restart_deployment",
    "rollout_restart_daemonset",
    "rollout_restart_statefulset",
    "restart_pod",
    # Pod/Deployment inspection helpers
    "get_deployment",
    "list_pods_for_deployment",
    "get_pod_container_states",
    "get_pod_logs",
]


def _kubeconfig_matches_cluster(kubeconfig_path: str, cluster: str) -> bool:
    """Checks whether kubeconfig appears to target the cluster and returns True/False (e.g., True), while unreadable files return False."""
    try:
        text = open(kubeconfig_path, "r", encoding="utf-8").read()
    except Exception:
        return False
    target = (cluster or "").strip().lower()
    if not target:
        return False
    lowered = text.lower()
    if target in lowered:
        return True
    marker = f"current-context: {target}"
    return marker in lowered


def _bool_env(name: str, default: bool) -> bool:
    """Reads boolean env var and returns True/False (e.g., True), while unknown values fall back to default."""
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _is_usable_kubeconfig(path: str) -> bool:
    """Checks kubeconfig file usability and returns True/False (e.g., True), while stat/read errors return False."""
    try:
        if not os.path.isfile(path):
            return False
        return os.path.getsize(path) > 0
    except Exception:
        return False


def _snapshot_okec_kubeconfig(cluster: str, source_path: str) -> Optional[str]:
    """Snapshots shared okec kubeconfig to a cluster-specific path and returns the saved path (e.g., ~/.kube/config.pc-cluster-1-phx-1), while copy failures return None."""
    name = (cluster or "").strip()
    src = (source_path or "").strip()
    if not name or not src or not os.path.isfile(src):
        return None
    dest = Path.home() / ".kube" / f"config.{name}"
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, str(dest))
        return str(dest)
    except Exception as exc:
        log("warning", "Failed to snapshot okec kubeconfig for cluster {}: {}", name, exc)
        return None


def _run_aws_command(args: List[str]) -> Tuple[Optional[Dict[str, Any]], str]:
    """Runs aws command using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not shutil.which("aws"):
        return None, "aws CLI not found in PATH"

    cmd = ["aws"] + args + ["--output", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            return None, proc.stderr.strip() or f"aws command exited {proc.returncode}"
        try:
            data = json.loads(proc.stdout or "{}")
        except Exception as je:
            return None, f"failed to parse AWS JSON: {je}"
        return data, ""
    except Exception as e:
        return None, str(e)


def get_active_clusters_by_account_id(account_id: str) -> List[Dict[str, Any]]:
    """Gets active clusters by account id using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    json_data, err = _run_aws_command([
        "ce", "cluster", "list",
        "--account-id", account_id,
        "--lifecycle-state", "ACTIVE"
    ])

    clusters = []
    if json_data is not None and "data" in json_data:
        for cluster_data in json_data["data"]:
            log("info", "Found cluster {} {}", cluster_data.get("name", ""), cluster_data.get("id", ""))
            clusters.append({
                "name": cluster_data.get("name", ""),
                "id": cluster_data.get("id", "")
            })

    if not clusters and err:
        log("error", "Failed to get active clusters: {}", err)

    return clusters


def _create_kubeconfig_for_cluster(cluster_id: str, cluster_name: str) -> Optional[str]:
    """Creates kubeconfig for cluster using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    kubeconfig_path = f"/tmp/{cluster_name}.kubeconfig"

    try:
        # Run aws ce cluster create-kubeconfig command with instance principal auth
        proc = subprocess.run([
            "aws", "ce", "cluster", "create-kubeconfig",
            "--cluster-id", cluster_id,
            "--file", kubeconfig_path
        ], capture_output=True, text=True, timeout=60)

        if proc.returncode == 0 and os.path.isfile(kubeconfig_path):
            log("info", "Successfully created kubeconfig for cluster {} at {}", cluster_name, kubeconfig_path)
            return kubeconfig_path
        else:
            error_msg = proc.stderr.strip() or f"aws command exited {proc.returncode}"
            log("error", "Failed to create kubeconfig for cluster {}: {}", cluster_name, error_msg)
            return None

    except Exception as e:
        log("error", "Exception creating kubeconfig for cluster {}: {}", cluster_name, e)
        return None


def _get_account_id_for_cluster(cluster: str) -> Optional[str]:
    """Gets account id for cluster using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    if "ss-cp" in cluster:
        return os.environ.get("CP_account_ID")
    else:
        return os.environ.get("DP_account_ID")


def get_kubeconfig_for_cluster(cluster: str, search_dirs: Optional[List[str]] = None, account_id: Optional[str] = None) -> Optional[str]:
    """Gets kubeconfig for cluster using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    # First try static file resolution
    candidates: List[str] = []
    bases: List[str] = []

    if isinstance(search_dirs, list):
        bases.extend(search_dirs)

    kc_dir = os.environ.get("KUBECONFIG_DIR")
    if kc_dir:
        bases.append(kc_dir)

    bases.append(os.path.expanduser("~/.kube"))
    bases.append("/kubeconfigs")

    for base in bases:
        for name in (f"config.{cluster}", f"config-{cluster}", cluster, f"{cluster}.config"):
            candidates.append(os.path.join(base, name))

    for p in candidates:
        try:
            if _is_usable_kubeconfig(p):
                log("info", "Found local kubeconfig for cluster {} at {}", cluster, p)
                return p
        except Exception:
            continue

    # Support OHAI okec workflow where kubeconfig is written to a shared path.
    # Use it only when it appears to match the requested cluster.
    okec_kubeconfig = os.path.expanduser("~/.kube/config-eks-connect.yaml")
    allow_okec_shared = _bool_env("CORTEX_KUBECONFIG_USE_OKEC_SHARED", False)
    if allow_okec_shared and _is_usable_kubeconfig(okec_kubeconfig) and _kubeconfig_matches_cluster(okec_kubeconfig, cluster):
        log("info", "Using okec kubeconfig for cluster {} at {}", cluster, okec_kubeconfig)
        snap = _snapshot_okec_kubeconfig(cluster, okec_kubeconfig)
        if snap:
            log("info", "Saved cluster kubeconfig snapshot for {} at {}", cluster, snap)
            return snap
        return okec_kubeconfig

    # Check for existing kubeconfig in /tmp before dynamic creation
    tmp_kubeconfig = f"/tmp/{cluster}.kubeconfig"
    if _is_usable_kubeconfig(tmp_kubeconfig):
        log("info", "Found existing kubeconfig for cluster {} in /tmp", cluster)
        return tmp_kubeconfig

    # Auto-determine account_id if not provided
    if account_id is None:
        account_id = _get_account_id_for_cluster(cluster)

    # If static files not found and account_id available, try dynamic creation
    if account_id:
        log("info", "Static kubeconfig not found for cluster {}, trying dynamic creation with account {}", cluster, account_id)

        try:
            active_clusters = get_active_clusters_by_account_id(account_id)

            # Find matching cluster by name
            matching_cluster = None
            for cluster_info in active_clusters:
                if cluster_info.get("name") == cluster:
                    matching_cluster = cluster_info
                    break

            if matching_cluster:
                cluster_id = matching_cluster.get("id")
                if cluster_id:
                    kubeconfig_path = _create_kubeconfig_for_cluster(cluster_id, cluster)
                    if kubeconfig_path:
                        return kubeconfig_path
                    else:
                        log("error", "Failed to create kubeconfig for cluster {}", cluster)
                else:
                    log("error", "Cluster {} found but missing ID", cluster)
            else:
                log("info", "Cluster {} not found in active clusters for account {}", cluster, account_id)

        except Exception as e:
            log("error", "Exception during dynamic kubeconfig creation for cluster {}: {}", cluster, e)

    return None


def kubectl_json(kubeconfig: str, args: List[str], timeout: int = 30) -> Tuple[Optional[Dict[str, Any]], str]:
    """Builds kubectl json using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not kubeconfig:
        return None, "missing kubeconfig"
    if not shutil.which("kubectl"):
        return None, "kubectl not found in PATH"

    cmd = ["kubectl", "--kubeconfig", kubeconfig] + args + ["-o", "json"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            return None, proc.stderr.strip() or f"kubectl exited {proc.returncode}"
        try:
            data = json.loads(proc.stdout or "{}")
        except Exception as je:
            return None, f"failed to parse kubectl JSON: {je}"
        if not isinstance(data, dict):
            return None, "unexpected kubectl output (not a JSON object)"
        return data, ""
    except Exception as e:
        return None, str(e)


def check_deployment_health(kubeconfig: str, namespace: str, deployment: str, timeout: int = 30) -> Dict[str, Any]:
    """Checks deployment health using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    obj, err = kubectl_json(kubeconfig, ["get", "deployment", deployment, "-n", namespace], timeout=timeout)
    if obj is None:
        return {"deployment": deployment, "namespace": namespace, "healthy": False, "error": err}

    spec = obj.get("spec", {}) or {}
    status = obj.get("status", {}) or {}

    desired = int(spec.get("replicas", status.get("replicas", 0)) or 0)
    ready = int(status.get("readyReplicas", 0) or 0)
    available = int(status.get("availableReplicas", 0) or 0)
    unavailable = int(status.get("unavailableReplicas", 0) or 0)
    conditions = status.get("conditions", [])

    healthy = (ready >= desired) and (unavailable == 0)

    return {
        "deployment": deployment,
        "namespace": namespace,
        "desired": desired,
        "ready": ready,
        "available": available,
        "unavailable": unavailable,
        "conditions": conditions,
        "healthy": bool(healthy),
    }


def _run_kubectl(kubeconfig: str, args: List[str], timeout: int = 60) -> Dict[str, Any]:
    """Runs kubectl using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not kubeconfig:
        return {"success": False, "code": -1, "stdout": "", "stderr": "missing kubeconfig"}
    if not shutil.which("kubectl"):
        return {"success": False, "code": -1, "stdout": "", "stderr": "kubectl not found in PATH"}
    cmd = ["kubectl", "--kubeconfig", kubeconfig] + args
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "success": proc.returncode == 0,
            "code": proc.returncode,
            "stdout": proc.stdout or "",
            "stderr": proc.stderr or "",
            "command": " ".join(cmd),
        }
    except Exception as e:
        return {"success": False, "code": -1, "stdout": "", "stderr": str(e), "command": " ".join(cmd)}


def _rollout_restart(kubeconfig: str, kind: str, namespace: str, name: str, timeout: int = 300) -> Dict[str, Any]:
    """Builds rollout restart using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    kind = kind.lower()
    if kind not in ("deployment", "daemonset", "statefulset"):
        return {"success": False, "error": f"unsupported kind: {kind}"}
    # Trigger restart
    r1 = _run_kubectl(kubeconfig, ["-n", namespace, "rollout", "restart", f"{kind}/{name}"], timeout=60)
    if not r1.get("success"):
        return {"success": False, "step": "restart", "result": r1}
    # Wait for rollout to complete
    r2 = _run_kubectl(kubeconfig, ["-n", namespace, "rollout", "status", f"{kind}/{name}", f"--timeout={timeout}s"], timeout=timeout + 30)
    if not r2.get("success"):
        return {"success": False, "step": "status", "restart_result": r1, "status_result": r2}
    return {"success": True, "restart_result": r1, "status_result": r2}


def rollout_restart_deployment(kubeconfig: str, namespace: str, name: str, timeout: int = 300) -> Dict[str, Any]:
    """Builds rollout restart deployment using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return _rollout_restart(kubeconfig, "deployment", namespace, name, timeout)


def rollout_restart_daemonset(kubeconfig: str, namespace: str, name: str, timeout: int = 300) -> Dict[str, Any]:
    """Builds rollout restart daemonset using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return _rollout_restart(kubeconfig, "daemonset", namespace, name, timeout)


def rollout_restart_statefulset(kubeconfig: str, namespace: str, name: str, timeout: int = 600) -> Dict[str, Any]:
    """Builds rollout restart statefulset using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return _rollout_restart(kubeconfig, "statefulset", namespace, name, timeout)


def restart_pod(kubeconfig: str, namespace: str, pod: str, timeout: int = 180) -> Dict[str, Any]:
    """Builds restart pod using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    res = _run_kubectl(kubeconfig, ["-n", namespace, "delete", f"pod/{pod}", "--wait=true"], timeout=timeout)
    res["deleted"] = bool(res.get("success"))
    return res


def get_deployment(kubeconfig: str, namespace: str, name: str, timeout: int = 30) -> Dict[str, Any]:
    """Gets deployment using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    obj, err = kubectl_json(kubeconfig, ["get", "deployment", name, "-n", namespace], timeout=timeout)
    if obj is None:
        return {"error": err or "failed to get deployment"}
    return obj


def _selector_from_deployment(dep_obj: Dict[str, Any]) -> Optional[str]:
    """Builds selector from deployment using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        sel = (dep_obj.get("spec") or {}).get("selector") or {}
        ml = sel.get("matchLabels") or {}
        if isinstance(ml, dict) and ml:
            parts = [f"{k}={v}" for k, v in ml.items()]
            return ",".join(parts)
    except Exception:
        return None
    return None


def list_pods_for_deployment(kubeconfig: str, namespace: str, name: str, timeout: int = 60) -> Dict[str, Any]:
    """Lists pods for deployment using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    dep = get_deployment(kubeconfig, namespace, name, timeout=timeout)
    if "error" in dep:
        return {"success": False, "error": dep["error"]}
    sel = _selector_from_deployment(dep)
    if not sel:
        return {"success": False, "error": "deployment has no matchLabels selector"}
    pods_obj, err = kubectl_json(kubeconfig, ["get", "pods", "-n", namespace, "-l", sel], timeout=timeout)
    if pods_obj is None:
        return {"success": False, "error": err or "failed to list pods"}
    items = pods_obj.get("items", []) if isinstance(pods_obj, dict) else []
    return {"success": True, "pods": items, "selector": sel}


def get_pod_container_states(pod_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Gets pod container states using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    out: List[Dict[str, Any]] = []
    try:
        statuses = ((pod_obj.get("status") or {}).get("containerStatuses")) or []
        for st in statuses:
            name = st.get("name", "")
            rc = int(st.get("restartCount", 0) or 0)
            state = st.get("state") or {}
            if "waiting" in state:
                reason = state["waiting"].get("reason", "")
                message = state["waiting"].get("message", "")
                out.append({"container": name, "state": "waiting", "reason": reason, "message": message, "restartCount": rc})
            elif "terminated" in state:
                reason = state["terminated"].get("reason", "")
                message = state["terminated"].get("message", "")
                out.append({"container": name, "state": "terminated", "reason": reason, "message": message, "restartCount": rc})
            elif "running" in state:
                # running has no reason/message, but include for completeness
                out.append({"container": name, "state": "running", "reason": "", "message": "", "restartCount": rc})
            else:
                out.append({"container": name, "state": "unknown", "reason": "", "message": "", "restartCount": rc})
    except Exception:
        pass
    return out


def get_pod_logs(
    kubeconfig: str,
    namespace: str,
    pod: str,
    container: Optional[str] = None,
    previous: bool = False,
    tail_lines: Optional[int] = None,
    timeout: int = 60,
) -> Dict[str, Any]:
    """Gets pod logs using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    args: List[str] = ["-n", namespace, "logs", pod]
    if container:
        args += ["-c", container]
    if previous:
        args.append("--previous")
    if isinstance(tail_lines, int) and tail_lines > 0:
        args.append(f"--tail={tail_lines}")
    return _run_kubectl(kubeconfig, args, timeout=timeout)
