"""Azure resource inventory — VMs, SQL databases, AKS, Load Balancers, Functions.

Uses azure-mgmt SDK when configured (DefaultAzureCredential — handles Managed
Identity, CLI, env vars automatically).  Falls back to a realistic demo scan.

Setup (.env):
    AZURE_SUBSCRIPTION_ID = xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    AZURE_RESOURCE_GROUP  = my-resource-group   (optional — scans all if unset)

    For local dev (one of):
      az login                                  (Azure CLI — easiest)
      AZURE_TENANT_ID + AZURE_CLIENT_ID + AZURE_CLIENT_SECRET  (service principal)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from ....core import get_logger
from ..base import ResourceItem, ScanResult

logger = get_logger(__name__)


def _azure_available() -> bool:
    try:
        from azure.identity import DefaultAzureCredential  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def _subscription() -> str:
    return os.getenv("AZURE_SUBSCRIPTION_ID", "").strip()


def _resource_group() -> str:
    return os.getenv("AZURE_RESOURCE_GROUP", "").strip()


def _credential():
    from azure.identity import DefaultAzureCredential  # type: ignore
    return DefaultAzureCredential()


# ── Real Azure scan ────────────────────────────────────────────────────────────

def _scan_real() -> ScanResult:
    result = ScanResult(cloud="azure")
    sub  = _subscription()
    rg   = _resource_group()
    errors = []
    cred = _credential()

    # Virtual Machines
    try:
        from azure.mgmt.compute import ComputeManagementClient  # type: ignore
        cc = ComputeManagementClient(cred, sub)
        vms = cc.virtual_machines.list_all() if not rg else cc.virtual_machines.list(rg)
        for vm in vms:
            location = vm.location or "unknown"
            tags = dict(vm.tags or {})
            result.resources.append(ResourceItem(
                id=vm.id, name=vm.name,
                resource_type="compute",
                region=location,
                compartment=rg or sub,
                status="unknown", tags=tags,
            ))
    except Exception as exc:
        errors.append(f"VMs: {exc}")

    # Azure SQL databases
    try:
        from azure.mgmt.sql import SqlManagementClient  # type: ignore
        sc = SqlManagementClient(cred, sub)
        servers = sc.servers.list() if not rg else sc.servers.list_by_resource_group(rg)
        for srv in servers:
            dbs = sc.databases.list_by_server(srv.id.split("/")[4], srv.name)
            for db in dbs:
                if db.name == "master":
                    continue
                result.resources.append(ResourceItem(
                    id=db.id, name=f"{srv.name}/{db.name}",
                    resource_type="database",
                    region=srv.location or "unknown",
                    compartment=rg or sub,
                    status="unknown",
                ))
    except Exception as exc:
        errors.append(f"SQL: {exc}")

    # AKS clusters
    try:
        from azure.mgmt.containerservice import ContainerServiceClient  # type: ignore
        csc = ContainerServiceClient(cred, sub)
        clusters = csc.managed_clusters.list() if not rg else csc.managed_clusters.list_by_resource_group(rg)
        for cl in clusters:
            result.resources.append(ResourceItem(
                id=cl.id, name=cl.name,
                resource_type="kubernetes",
                region=cl.location or "unknown",
                compartment=rg or sub,
                status="unknown",
            ))
    except Exception as exc:
        errors.append(f"AKS: {exc}")

    # Load Balancers
    try:
        from azure.mgmt.network import NetworkManagementClient  # type: ignore
        nc = NetworkManagementClient(cred, sub)
        lbs = nc.load_balancers.list_all() if not rg else nc.load_balancers.list(rg)
        for lb in lbs:
            result.resources.append(ResourceItem(
                id=lb.id, name=lb.name,
                resource_type="lb",
                region=lb.location or "unknown",
                compartment=rg or sub,
                status="unknown",
            ))
    except Exception as exc:
        errors.append(f"Load Balancers: {exc}")

    # Function Apps
    try:
        from azure.mgmt.web import WebSiteManagementClient  # type: ignore
        wc = WebSiteManagementClient(cred, sub)
        apps = wc.web_apps.list() if not rg else wc.web_apps.list_by_resource_group(rg)
        for app in apps:
            if app.kind and "functionapp" in app.kind.lower():
                result.resources.append(ResourceItem(
                    id=app.id, name=app.name,
                    resource_type="compute",
                    region=app.location or "unknown",
                    compartment=rg or sub,
                    status="unknown",
                ))
    except Exception as exc:
        errors.append(f"Function Apps: {exc}")

    # Check Azure Monitor alerts for coverage
    _check_monitor_coverage(result.resources, cred, sub)

    result.errors = errors
    return result


def _check_monitor_coverage(resources: list[ResourceItem], cred: object, sub: str) -> None:
    try:
        from azure.mgmt.monitor import MonitorManagementClient  # type: ignore
        mc = MonitorManagementClient(cred, sub)
        alert_rules = list(mc.metric_alerts.list_by_subscription())
        monitored_ids: set[str] = set()
        for rule in alert_rules:
            if rule.enabled:
                for scope in (rule.scopes or []):
                    monitored_ids.add(scope.lower())

        for r in resources:
            rid_lower = (r.id or "").lower()
            if rid_lower in monitored_ids:
                r.status = "monitored"
                r.monitoring_sources = ["Azure Monitor"]
                r.alarm_count = 1
            else:
                r.status = "unmonitored"
    except Exception as exc:
        logger.debug("Azure Monitor coverage check failed: %s", exc)
        for r in resources:
            r.status = "unknown"


# ── Demo scan ─────────────────────────────────────────────────────────────────

_DEMO_RESOURCES = [
    ("/subscriptions/demo/resourceGroups/prod-rg/providers/Microsoft.Compute/virtualMachines/web-vm-01", "web-vm-01", "compute", "eastus", "monitored", ["Azure Monitor", "Log Analytics"], 2),
    ("/subscriptions/demo/resourceGroups/prod-rg/providers/Microsoft.Compute/virtualMachines/web-vm-02", "web-vm-02", "compute", "eastus", "monitored", ["Azure Monitor"], 1),
    ("/subscriptions/demo/resourceGroups/prod-rg/providers/Microsoft.Compute/virtualMachines/worker-01", "worker-01", "compute", "eastus", "partial", ["Azure Monitor"], 0),
    ("/subscriptions/demo/resourceGroups/prod-rg/providers/Microsoft.Compute/virtualMachines/worker-02", "worker-02", "compute", "westus", "unmonitored", [], 0),
    ("/subscriptions/demo/resourceGroups/prod-rg/providers/Microsoft.Sql/servers/prod-sql/databases/main", "prod-sql/main", "database", "eastus", "monitored", ["Azure Monitor", "SQL Insights"], 3),
    ("/subscriptions/demo/resourceGroups/prod-rg/providers/Microsoft.Sql/servers/analytics-sql/databases/dw", "analytics-sql/dw", "database", "eastus", "unmonitored", [], 0),
    ("/subscriptions/demo/resourceGroups/prod-rg/providers/Microsoft.ContainerService/managedClusters/prod-aks", "prod-aks", "kubernetes", "eastus", "monitored", ["Azure Monitor", "Container Insights", "Prometheus"], 4),
    ("/subscriptions/demo/resourceGroups/staging-rg/providers/Microsoft.ContainerService/managedClusters/staging-aks", "staging-aks", "kubernetes", "eastus2", "partial", ["Azure Monitor"], 1),
    ("/subscriptions/demo/resourceGroups/prod-rg/providers/Microsoft.Network/loadBalancers/prod-lb", "prod-lb", "lb", "eastus", "monitored", ["Azure Monitor"], 2),
    ("/subscriptions/demo/resourceGroups/prod-rg/providers/Microsoft.Network/loadBalancers/internal-lb", "internal-lb", "lb", "eastus", "unmonitored", [], 0),
    ("/subscriptions/demo/resourceGroups/prod-rg/providers/Microsoft.Web/sites/process-orders-fn", "process-orders-fn", "compute", "eastus", "partial", ["Application Insights"], 0),
    ("/subscriptions/demo/resourceGroups/prod-rg/providers/Microsoft.Web/sites/send-notifications-fn", "send-notifications-fn", "compute", "eastus", "unknown", [], 0),
]


def _scan_demo() -> ScanResult:
    result = ScanResult(cloud="azure")
    sub = _subscription() or "demo-subscription"
    for rid, name, rtype, region, status, sources, alarms in _DEMO_RESOURCES:
        result.resources.append(ResourceItem(
            id=rid, name=name, resource_type=rtype,
            region=region, compartment=sub,
            status=status, monitoring_sources=list(sources),
            alarm_count=alarms,
        ))
    return result


# ── Public entry point ────────────────────────────────────────────────────────

def run_scan(*, region: str = "", demo: bool = False) -> ScanResult:
    t0 = time.time()

    if demo or not _azure_available() or not _subscription():
        if not demo:
            logger.info("Azure SDK not available or AZURE_SUBSCRIPTION_ID not set — running demo scan")
        result = _scan_demo()
    else:
        logger.info("Starting real Azure scan: subscription=%s rg=%s", _subscription(), _resource_group() or "all")
        try:
            result = _scan_real()
        except Exception as exc:
            logger.error("Azure scan failed: %s — falling back to demo", exc)
            result = _scan_demo()
            result.errors.append(f"Real scan failed: {exc}")

    result.scan_duration_seconds = time.time() - t0
    logger.info(
        "Azure scan complete: %d resources (%d monitored, %d unmonitored) in %.1fs",
        len(result.resources), len(result.monitored),
        len(result.unmonitored), result.scan_duration_seconds,
    )
    return result
