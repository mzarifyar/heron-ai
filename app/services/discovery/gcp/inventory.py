"""GCP resource inventory — Compute Engine, Cloud SQL, GKE, Load Balancers, Cloud Functions.

Uses google-cloud SDK when configured (Application Default Credentials or
service account key).  Falls back to a realistic demo scan.

Setup (.env):
    GCP_PROJECT_ID       = my-project-123
    GCP_REGION           = us-central1          (optional — scans all regions if unset)
    GOOGLE_APPLICATION_CREDENTIALS = /path/to/key.json   (optional — uses ADC if unset)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from ....core import get_logger
from ..base import ResourceItem, ScanResult

logger = get_logger(__name__)


def _gcp_available() -> bool:
    try:
        import google.cloud.compute_v1  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def _project() -> str:
    return os.getenv("GCP_PROJECT_ID", "").strip()


def _region() -> str:
    return os.getenv("GCP_REGION", "us-central1").strip()


# ── Real GCP scan ──────────────────────────────────────────────────────────────

def _scan_real() -> ScanResult:
    result = ScanResult(cloud="gcp")
    project = _project()
    region  = _region()
    errors  = []

    # Compute Engine instances
    try:
        from google.cloud import compute_v1  # type: ignore
        agg_client = compute_v1.InstancesClient()
        for zone_name, zone_data in agg_client.aggregated_list(project=project):
            for inst in zone_data.instances or []:
                if inst.status not in ("RUNNING", "STOPPED"):
                    continue
                name_tag = inst.name
                labels = dict(inst.labels or {})
                result.resources.append(ResourceItem(
                    id=inst.self_link, name=name_tag,
                    resource_type="compute",
                    region=zone_name.split("/")[-1],
                    compartment=project,
                    status="unknown", tags=labels,
                ))
    except Exception as exc:
        errors.append(f"Compute Engine: {exc}")

    # Cloud SQL instances
    try:
        import googleapiclient.discovery  # type: ignore
        sql = googleapiclient.discovery.build("sqladmin", "v1beta4")
        resp = sql.instances().list(project=project).execute()
        for inst in resp.get("items", []):
            if inst.get("state") in ("STOPPED", "SUSPENDED"):
                continue
            result.resources.append(ResourceItem(
                id=inst["selfLink"], name=inst["name"],
                resource_type="database",
                region=inst.get("region", region),
                compartment=project,
                status="unknown",
            ))
    except Exception as exc:
        errors.append(f"Cloud SQL: {exc}")

    # GKE clusters
    try:
        from google.cloud import container_v1  # type: ignore
        cluster_client = container_v1.ClusterManagerClient()
        parent = f"projects/{project}/locations/-"
        resp = cluster_client.list_clusters(parent=parent)
        for cl in resp.clusters:
            result.resources.append(ResourceItem(
                id=cl.self_link, name=cl.name,
                resource_type="kubernetes",
                region=cl.location,
                compartment=project,
                status="unknown",
            ))
    except Exception as exc:
        errors.append(f"GKE: {exc}")

    # Cloud Load Balancers (forwarding rules as proxy)
    try:
        from google.cloud import compute_v1  # type: ignore
        fwd_client = compute_v1.GlobalForwardingRulesClient()
        for rule in fwd_client.list(project=project):
            result.resources.append(ResourceItem(
                id=rule.self_link, name=rule.name,
                resource_type="lb",
                region="global",
                compartment=project,
                status="unknown",
            ))
    except Exception as exc:
        errors.append(f"Load Balancer: {exc}")

    # Cloud Functions
    try:
        from google.cloud import functions_v1  # type: ignore
        fn_client = functions_v1.CloudFunctionsServiceClient()
        parent = f"projects/{project}/locations/-"
        for fn in fn_client.list_functions(request={"parent": parent}):
            result.resources.append(ResourceItem(
                id=fn.name, name=fn.name.split("/")[-1],
                resource_type="compute",
                region=fn.name.split("/")[3],
                compartment=project,
                status="unknown",
            ))
    except Exception as exc:
        errors.append(f"Cloud Functions: {exc}")

    # Check Cloud Monitoring alerting policies for coverage
    _check_monitoring_coverage(result.resources, project)

    result.errors = errors
    return result


def _check_monitoring_coverage(resources: list[ResourceItem], project: str) -> None:
    try:
        from google.cloud import monitoring_v3  # type: ignore
        client = monitoring_v3.AlertPolicyServiceClient()
        name = f"projects/{project}"
        policies = list(client.list_alert_policies(name=name))
        monitored_names: set[str] = set()
        for policy in policies:
            if policy.enabled:
                for condition in policy.conditions:
                    # Extract resource name hints from condition filter
                    filt = condition.condition_threshold.filter if hasattr(condition, "condition_threshold") else ""
                    monitored_names.add(filt[:50])

        for r in resources:
            if any(r.name in m for m in monitored_names):
                r.status = "monitored"
                r.monitoring_sources = ["Cloud Monitoring"]
                r.alarm_count = 1
            else:
                r.status = "unmonitored"
    except Exception as exc:
        logger.debug("GCP monitoring coverage check failed: %s", exc)
        for r in resources:
            r.status = "unknown"


# ── Demo scan ─────────────────────────────────────────────────────────────────

_DEMO_RESOURCES = [
    ("projects/demo/zones/us-central1-a/instances/web-vm-01", "web-vm-01", "compute", "us-central1-a", "monitored", ["Cloud Monitoring", "Node Exporter"], 2),
    ("projects/demo/zones/us-central1-a/instances/web-vm-02", "web-vm-02", "compute", "us-central1-a", "monitored", ["Cloud Monitoring"], 1),
    ("projects/demo/zones/us-central1-b/instances/worker-vm-01", "worker-vm-01", "compute", "us-central1-b", "partial", ["Cloud Monitoring"], 0),
    ("projects/demo/zones/us-central1-b/instances/worker-vm-02", "worker-vm-02", "compute", "us-central1-b", "unmonitored", [], 0),
    ("projects/demo/instances/prod-postgres", "prod-postgres", "database", "us-central1", "monitored", ["Cloud Monitoring", "Cloud SQL Insights"], 3),
    ("projects/demo/instances/analytics-postgres", "analytics-postgres", "database", "us-central1", "unmonitored", [], 0),
    ("projects/demo/locations/us-central1/clusters/prod-gke", "prod-gke", "kubernetes", "us-central1", "monitored", ["Cloud Monitoring", "Prometheus", "GKE Workload Metrics"], 4),
    ("projects/demo/locations/us-east1/clusters/staging-gke", "staging-gke", "kubernetes", "us-east1", "partial", ["Cloud Monitoring"], 1),
    ("projects/demo/global/forwardingRules/prod-lb", "prod-lb", "lb", "global", "monitored", ["Cloud Monitoring"], 2),
    ("projects/demo/global/forwardingRules/internal-lb", "internal-lb", "lb", "global", "unmonitored", [], 0),
    ("projects/demo/locations/us-central1/functions/process-events", "process-events", "compute", "us-central1", "partial", ["Cloud Logging"], 0),
    ("projects/demo/locations/us-central1/functions/send-emails", "send-emails", "compute", "us-central1", "unknown", [], 0),
]


def _scan_demo() -> ScanResult:
    result = ScanResult(cloud="gcp")
    project = _project() or "demo-project"
    for rid, name, rtype, region, status, sources, alarms in _DEMO_RESOURCES:
        result.resources.append(ResourceItem(
            id=rid, name=name, resource_type=rtype,
            region=region, compartment=project,
            status=status, monitoring_sources=list(sources),
            alarm_count=alarms,
        ))
    return result


# ── Public entry point ────────────────────────────────────────────────────────

def run_scan(*, region: str = "", demo: bool = False) -> ScanResult:
    t0 = time.time()
    if region:
        os.environ["GCP_REGION"] = region

    if demo or not _gcp_available() or not _project():
        if not demo:
            logger.info("GCP SDK not available or GCP_PROJECT_ID not set — running demo scan")
        result = _scan_demo()
    else:
        logger.info("Starting real GCP scan: project=%s region=%s", _project(), _region())
        try:
            result = _scan_real()
        except Exception as exc:
            logger.error("GCP scan failed: %s — falling back to demo", exc)
            result = _scan_demo()
            result.errors.append(f"Real scan failed: {exc}")

    result.scan_duration_seconds = time.time() - t0
    logger.info(
        "GCP scan complete: %d resources (%d monitored, %d unmonitored) in %.1fs",
        len(result.resources), len(result.monitored),
        len(result.unmonitored), result.scan_duration_seconds,
    )
    return result
