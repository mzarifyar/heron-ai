"""AWS resource inventory — EC2, RDS, EKS, ELB, and Lambda.

Uses boto3 when configured (instance profile or env vars).  Falls back to
a realistic demo scan so the Discovery page works without AWS credentials.

Setup (.env):
    AWS_REGION              = us-east-1
    AWS_ACCESS_KEY_ID       = ...   (optional — instance profile preferred)
    AWS_SECRET_ACCESS_KEY   = ...
    AWS_ACCOUNT_ID          = 123456789012  (optional — for display)
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from ....core import get_logger
from ..base import ResourceItem, ScanResult

logger = get_logger(__name__)


def _boto3_available() -> bool:
    try:
        import boto3  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


def _region() -> str:
    return os.getenv("AWS_REGION", "us-east-1")


def _account_id() -> str:
    return os.getenv("AWS_ACCOUNT_ID", "unknown-account")


def _client(service: str):
    import boto3  # type: ignore
    return boto3.client(service, region_name=_region())


# ── Real AWS scan ──────────────────────────────────────────────────────────────

def _scan_real() -> ScanResult:
    result = ScanResult(cloud="aws")
    region = _region()
    account = _account_id()
    errors = []

    # EC2 instances
    try:
        ec2 = _client("ec2")
        resp = ec2.describe_instances(Filters=[{"Name": "instance-state-name", "Values": ["running", "stopped"]}])
        for reservation in resp.get("Reservations", []):
            for inst in reservation.get("Instances", []):
                name_tag = next((t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"), inst["InstanceId"])
                tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
                result.resources.append(ResourceItem(
                    id=inst["InstanceId"], name=name_tag,
                    resource_type="compute", region=region, compartment=account,
                    status="unknown", tags=tags,
                ))
    except Exception as exc:
        errors.append(f"EC2: {exc}")

    # RDS instances
    try:
        rds = _client("rds")
        resp = rds.describe_db_instances()
        for db in resp.get("DBInstances", []):
            if db.get("DBInstanceStatus") in ("deleting", "deleted"):
                continue
            result.resources.append(ResourceItem(
                id=db["DBInstanceArn"], name=db["DBInstanceIdentifier"],
                resource_type="database", region=region, compartment=account,
                status="unknown",
            ))
    except Exception as exc:
        errors.append(f"RDS: {exc}")

    # EKS clusters
    try:
        eks = _client("eks")
        cluster_names = eks.list_clusters().get("clusters", [])
        for name in cluster_names:
            info = eks.describe_cluster(name=name)["cluster"]
            result.resources.append(ResourceItem(
                id=info.get("arn", name), name=name,
                resource_type="kubernetes", region=region, compartment=account,
                status="unknown",
            ))
    except Exception as exc:
        errors.append(f"EKS: {exc}")

    # ALB / NLB load balancers
    try:
        elb = _client("elbv2")
        lbs = elb.describe_load_balancers().get("LoadBalancers", [])
        for lb in lbs:
            if lb.get("State", {}).get("Code") in ("deleting", "deleted"):
                continue
            result.resources.append(ResourceItem(
                id=lb["LoadBalancerArn"], name=lb["LoadBalancerName"],
                resource_type="lb", region=region, compartment=account,
                status="unknown",
            ))
    except Exception as exc:
        errors.append(f"ELB: {exc}")

    # Lambda functions
    try:
        lam = _client("lambda")
        paginator = lam.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                result.resources.append(ResourceItem(
                    id=fn["FunctionArn"], name=fn["FunctionName"],
                    resource_type="compute", region=region, compartment=account,
                    status="unknown",
                    tags={"runtime": fn.get("Runtime", "")},
                ))
    except Exception as exc:
        errors.append(f"Lambda: {exc}")

    # S3 buckets (storage with golden signal metrics: latency, throughput, errors, traffic)
    try:
        s3 = _client("s3")
        buckets = s3.list_buckets().get("Buckets", [])
        for bucket in buckets:
            bucket_name = bucket["Name"]
            result.resources.append(ResourceItem(
                id=f"arn:aws:s3:::{bucket_name}", name=bucket_name,
                resource_type="storage", region=region, compartment=account,
                status="unknown",
                tags={"bucket": bucket_name},
            ))
    except Exception as exc:
        errors.append(f"S3: {exc}")

    # Check CloudWatch alarms to determine monitoring status
    _check_cloudwatch_coverage(result.resources, region)

    result.errors = errors
    return result


def _check_cloudwatch_coverage(resources: list[ResourceItem], region: str) -> None:
    """Query CloudWatch to determine which resources have active alarms."""
    try:
        import boto3  # type: ignore
        cw = boto3.client("cloudwatch", region_name=region)
        paginator = cw.get_paginator("describe_alarms")
        alarm_dims: set[str] = set()
        for page in paginator.paginate(StateValue="OK"):
            for alarm in page.get("MetricAlarms", []):
                for d in alarm.get("Dimensions", []):
                    alarm_dims.add(d["Value"])
        alarm_dims_firing: set[str] = set()
        for page in paginator.paginate(StateValue="ALARM"):
            for alarm in page.get("MetricAlarms", []):
                for d in alarm.get("Dimensions", []):
                    alarm_dims_firing.add(d["Value"])

        for r in resources:
            short_id = r.id.split("/")[-1].split(":")[-1]
            if short_id in alarm_dims_firing:
                r.status = "monitored"
                r.alarm_count = 1
                r.monitoring_sources = ["CloudWatch"]
            elif short_id in alarm_dims:
                r.status = "monitored"
                r.monitoring_sources = ["CloudWatch"]
            else:
                r.status = "unmonitored"
    except Exception as exc:
        logger.debug("CloudWatch coverage check failed: %s", exc)
        for r in resources:
            r.status = "unknown"


# ── Demo scan ─────────────────────────────────────────────────────────────────

_DEMO_RESOURCES = [
    ("i-0abc123def456", "web-server-01", "compute", "monitored", ["CloudWatch", "Node Exporter"], 2),
    ("i-0abc123def457", "web-server-02", "compute", "monitored", ["CloudWatch", "Node Exporter"], 1),
    ("i-0abc123def458", "worker-01", "compute", "partial", ["CloudWatch"], 0),
    ("i-0abc123def459", "worker-02", "compute", "unmonitored", [], 0),
    ("arn:aws:rds:us-east-1:prod-postgres", "prod-postgres", "database", "monitored", ["CloudWatch", "RDS Insights"], 3),
    ("arn:aws:rds:us-east-1:analytics-mysql", "analytics-mysql", "database", "unmonitored", [], 0),
    ("arn:aws:eks:us-east-1:prod-cluster", "prod-eks-cluster", "kubernetes", "monitored", ["CloudWatch", "Prometheus", "kube-state-metrics"], 4),
    ("arn:aws:eks:us-east-1:staging-cluster", "staging-eks-cluster", "kubernetes", "partial", ["CloudWatch"], 1),
    ("arn:aws:elasticloadbalancing:alb-prod", "prod-alb", "lb", "monitored", ["CloudWatch"], 2),
    ("arn:aws:elasticloadbalancing:nlb-internal", "internal-nlb", "lb", "unmonitored", [], 0),
    ("arn:aws:lambda:process-orders", "process-orders", "compute", "partial", ["CloudWatch Logs"], 0),
    ("arn:aws:lambda:send-notifications", "send-notifications", "compute", "unknown", [], 0),
]


def _scan_demo() -> ScanResult:
    result = ScanResult(cloud="aws")
    region = _region()
    account = "123456789012"
    for rid, name, rtype, status, sources, alarms in _DEMO_RESOURCES:
        result.resources.append(ResourceItem(
            id=rid, name=name, resource_type=rtype,
            region=region, compartment=account,
            status=status, monitoring_sources=list(sources),
            alarm_count=alarms,
        ))
    return result


# ── Public entry point ────────────────────────────────────────────────────────

def run_scan(*, region: str = "", demo: bool = False) -> ScanResult:
    t0 = time.time()
    if region:
        os.environ["AWS_REGION"] = region

    if demo or not _boto3_available():
        if not demo:
            logger.info("boto3 not available — running AWS demo scan")
        result = _scan_demo()
    else:
        logger.info("Starting real AWS scan: region=%s account=%s", _region(), _account_id())
        try:
            result = _scan_real()
        except Exception as exc:
            logger.error("AWS scan failed: %s — falling back to demo", exc)
            result = _scan_demo()
            result.errors.append(f"Real scan failed: {exc}")

    result.scan_duration_seconds = time.time() - t0
    logger.info(
        "AWS scan complete: %d resources (%d monitored, %d unmonitored) in %.1fs",
        len(result.resources), len(result.monitored),
        len(result.unmonitored), result.scan_duration_seconds,
    )
    return result
