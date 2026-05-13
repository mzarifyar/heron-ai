"""OCI resource inventory — lists compute, DB, K8s, LB, network resources.

Uses the OCI Python SDK when available and configured.  Falls back to a
realistic simulated scan so the Discovery page is always functional for demos.

Real OCI credentials come from Instance Principals (on OCI VMs) or from:
    OCI_TENANCY_OCID, OCI_USER_OCID, OCI_FINGERPRINT,
    OCI_KEY_FILE, OCI_REGION  (env vars)
"""

from __future__ import annotations

import os
import time
from typing import Any
from uuid import uuid4

from ....core import get_logger
from ..base import ResourceItem, ScanResult

logger = get_logger(__name__)


def _oci_available() -> bool:
    try:
        import oci  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def _env(key: str) -> str:
    return os.getenv(key, "").strip()


def _make_config() -> Any:
    """Build OCI config from env vars or fall back to ~/.oci/config."""
    import oci  # type: ignore
    tenancy = _env("OCI_TENANCY_OCID")
    if tenancy:
        return {
            "tenancy": tenancy,
            "user": _env("OCI_USER_OCID"),
            "fingerprint": _env("OCI_FINGERPRINT"),
            "key_file": _env("OCI_KEY_FILE"),
            "region": _env("OCI_REGION") or "us-ashburn-1",
        }
    # Fall back to file-based config
    return oci.config.from_file()


# ── Real OCI scan ──────────────────────────────────────────────────────────

def _scan_real(region: str, compartment_id: str) -> ScanResult:
    import oci  # type: ignore
    result = ScanResult(cloud="oci")
    cfg = _make_config()
    errors: list[str] = []

    # Compute instances
    try:
        cc = oci.core.ComputeClient(cfg)
        instances = oci.pagination.list_call_get_all_results(
            cc.list_instances, compartment_id=compartment_id
        ).data
        for inst in instances:
            if inst.lifecycle_state in ("TERMINATING", "TERMINATED"):
                continue
            result.resources.append(ResourceItem(
                id=inst.id, name=inst.display_name or inst.id,
                resource_type="compute",
                region=region, compartment=compartment_id,
                status="unknown",
                tags=dict(inst.freeform_tags or {}),
            ))
    except Exception as exc:
        errors.append(f"compute: {exc}")

    # Autonomous databases
    try:
        dc = oci.database.DatabaseClient(cfg)
        dbs = oci.pagination.list_call_get_all_results(
            dc.list_autonomous_databases, compartment_id=compartment_id
        ).data
        for db in dbs:
            if db.lifecycle_state in ("TERMINATING", "TERMINATED"):
                continue
            result.resources.append(ResourceItem(
                id=db.id, name=db.display_name or db.id,
                resource_type="database",
                region=region, compartment=compartment_id,
                status="unknown",
                tags=dict(db.freeform_tags or {}),
            ))
    except Exception as exc:
        errors.append(f"database: {exc}")

    # OKE clusters
    try:
        ce = oci.container_engine.ContainerEngineClient(cfg)
        clusters = oci.pagination.list_call_get_all_results(
            ce.list_clusters, compartment_id=compartment_id
        ).data
        for cl in clusters:
            if cl.lifecycle_state in ("DELETING", "DELETED"):
                continue
            result.resources.append(ResourceItem(
                id=cl.id, name=cl.name or cl.id,
                resource_type="kubernetes",
                region=region, compartment=compartment_id,
                status="unknown",
            ))
    except Exception as exc:
        errors.append(f"kubernetes: {exc}")

    # Load balancers
    try:
        lbc = oci.load_balancer.LoadBalancerClient(cfg)
        lbs = oci.pagination.list_call_get_all_results(
            lbc.list_load_balancers, compartment_id=compartment_id
        ).data
        for lb in lbs:
            if lb.lifecycle_state in ("DELETING", "DELETED"):
                continue
            result.resources.append(ResourceItem(
                id=lb.id, name=lb.display_name or lb.id,
                resource_type="lb", region=region, compartment=compartment_id,
                status="unknown",
            ))
    except Exception as exc:
        errors.append(f"load_balancer: {exc}")

    result.errors = errors
    return result


def _check_oci_alarms(resources: list[ResourceItem], compartment_id: str, cfg: Any) -> None:
    """Query OCI Monitoring for alarms per resource and update status."""
    try:
        import oci  # type: ignore
        mc = oci.monitoring.MonitoringClient(cfg)
        alarms = oci.pagination.list_call_get_all_results(
            mc.list_alarms, compartment_id=compartment_id
        ).data
        alarm_resource_ids: set[str] = set()
        for alarm in alarms:
            if alarm.lifecycle_state == "ACTIVE":
                # OCI alarms target a namespace+query, not a specific resource OCID
                # We approximate: if the alarm's namespace matches a resource type, mark it
                alarm_resource_ids.add(alarm.namespace)
        for r in resources:
            type_ns_map = {
                "compute": "oci_computeagent",
                "database": "oci_autonomous_database",
                "kubernetes": "oci_oke",
                "lb": "oci_lbaas",
            }
            ns = type_ns_map.get(r.resource_type, "")
            if ns and ns in alarm_resource_ids:
                r.alarm_count = 1
                r.monitoring_sources.append("OCI Monitoring")
                r.metric_namespaces.append(ns)
                r.status = "monitored"
            else:
                r.metric_namespaces.append(ns) if ns else None
                r.status = "unmonitored"
    except Exception as exc:
        logger.debug("OCI alarm check failed: %s", exc)
        for r in resources:
            r.status = "unknown"


# ── Simulated scan (demo / no SDK) ─────────────────────────────────────────

_DEMO_RESOURCES = [
    ("ocid1.instance.oc1.phx.aaaa", "web-server-01", "compute", "us-phoenix-1", "monitored", ["OCI Monitoring", "Node Exporter"], 3),
    ("ocid1.instance.oc1.phx.bbbb", "web-server-02", "compute", "us-phoenix-1", "monitored", ["OCI Monitoring", "Node Exporter"], 2),
    ("ocid1.instance.oc1.phx.cccc", "worker-node-01", "compute", "us-phoenix-1", "partial", ["OCI Monitoring"], 1),
    ("ocid1.instance.oc1.phx.dddd", "worker-node-02", "compute", "us-phoenix-1", "unmonitored", [], 0),
    ("ocid1.autonomousdatabase.oc1.phx.aaaa", "prod-adb-01", "database", "us-phoenix-1", "monitored", ["OCI Monitoring"], 4),
    ("ocid1.autonomousdatabase.oc1.phx.bbbb", "analytics-adb-01", "database", "us-phoenix-1", "unmonitored", [], 0),
    ("ocid1.cluster.oc1.phx.aaaa", "prod-oke-cluster", "kubernetes", "us-phoenix-1", "monitored", ["OCI Monitoring", "Prometheus", "kube-state-metrics"], 5),
    ("ocid1.cluster.oc1.phx.bbbb", "dev-oke-cluster", "kubernetes", "us-phoenix-1", "partial", ["Prometheus"], 0),
    ("ocid1.loadbalancer.oc1.phx.aaaa", "prod-lb-01", "lb", "us-phoenix-1", "monitored", ["OCI Monitoring", "HAProxy Exporter"], 2),
    ("ocid1.loadbalancer.oc1.phx.bbbb", "internal-lb-01", "lb", "us-phoenix-1", "unmonitored", [], 0),
    ("ocid1.vcn.oc1.phx.aaaa", "prod-vcn", "network", "us-phoenix-1", "unknown", [], 0),
    ("ocid1.subnet.oc1.phx.aaaa", "prod-subnet-01", "network", "us-phoenix-1", "unknown", [], 0),
]


def _scan_demo() -> ScanResult:
    """Generate a realistic-looking demo scan for environments without OCI SDK."""
    result = ScanResult(cloud="oci")
    for rid, name, rtype, region, status, sources, alarms in _DEMO_RESOURCES:
        ns_map = {
            "compute": ["oci_computeagent"],
            "database": ["oci_autonomous_database"],
            "kubernetes": ["oci_oke", "kube_pod"],
            "lb": ["oci_lbaas"],
            "network": [],
        }
        result.resources.append(ResourceItem(
            id=rid, name=name, resource_type=rtype,
            region=region, compartment="ocid1.compartment.oc1..prod",
            status=status, monitoring_sources=list(sources),
            alarm_count=alarms,
            metric_namespaces=ns_map.get(rtype, []),
        ))
    result.errors = []
    return result


# ── Public entry point ─────────────────────────────────────────────────────

def run_scan(
    *,
    region: str = "",
    compartment_id: str = "",
    demo: bool = False,
) -> ScanResult:
    """Run OCI inventory scan.  Falls back to demo if SDK not installed."""
    t0 = time.time()
    region = region or _env("OCI_REGION") or "us-ashburn-1"
    compartment_id = compartment_id or _env("OCI_COMPARTMENT_ID") or ""

    if demo or not _oci_available() or not compartment_id:
        if not demo:
            logger.info("OCI SDK not available or COMPARTMENT_ID not set — running demo scan")
        result = _scan_demo()
    else:
        logger.info("Starting real OCI scan: region=%s compartment=%s", region, compartment_id)
        try:
            result = _scan_real(region, compartment_id)
            cfg = _make_config()
            _check_oci_alarms(result.resources, compartment_id, cfg)
        except Exception as exc:
            logger.error("OCI scan failed: %s — falling back to demo", exc)
            result = _scan_demo()
            result.errors.append(f"Real scan failed: {exc}")

    result.scan_duration_seconds = time.time() - t0
    logger.info(
        "OCI scan complete: %d resources (%d monitored, %d unmonitored) in %.1fs",
        len(result.resources), len(result.monitored),
        len(result.unmonitored), result.scan_duration_seconds,
    )
    return result
