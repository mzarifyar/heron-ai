#!/usr/bin/env python3
"""
Cortex synthetic data seeder.

Populates the database with rich, realistic incident data so every dashboard
widget, chart, and table looks like a live production system.

Usage:
    python scripts/seed_data.py [--reset]   # --reset clears existing seeded data first

Idempotent: running twice without --reset does not create duplicates.
"""

from __future__ import annotations

import argparse
import os
import sys
import random
import textwrap
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

# ── bootstrap path ──────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app.db.base import engine, init_db, SessionLocal  # noqa: E402
from app.db.models import (  # noqa: E402
    Action, Annotation, ClusterInventory, Incident, Integration,
    LearnOutcome, NearMiss, Postmortem, PullerRun, Recommendation,
    ServiceEdgeMetric, Signal, TimelineEvent,
)

# Fixed seed for reproducible IDs
rng = random.Random(42)


# ══════════════════════════════════════════════════════════════════════════════
# DATA DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════════

SERVICES = [
    "api-gateway", "auth-service", "payment-processor",
    "recommendation-engine", "data-pipeline", "notification-service",
    "search-service", "user-profile", "inventory-service", "checkout-service",
]

REGIONS = ["us-east-1", "us-west-2", "eu-west-1"]
ENVS = {"prod": 0.7, "staging": 0.2, "dev": 0.1}

INCIDENT_SPECS = [
    {
        "id": "seed-inc-001",
        "title": "High error rate on payment-processor in us-east-1",
        "severity": "sev1", "status": "resolved", "service": "payment-processor",
        "region": "us-east-1", "env": "prod", "auto_healed": True,
        "duration_min": 7, "days_ago": 2,
        "annotations": [
            ("alex.chen", "Checked ELB access logs — spike started at 14:23 UTC, correlates with the 14:20 deploy."),
            ("priya.k", "Confirmed: rollback triggered automatically. Error rate back to baseline."),
        ],
    },
    {
        "id": "seed-inc-002",
        "title": "Memory leak on auth-service — pod OOM killed in us-east-1",
        "severity": "sev1", "status": "resolved", "service": "auth-service",
        "region": "us-east-1", "env": "prod", "auto_healed": True,
        "duration_min": 12, "days_ago": 5,
        "annotations": [
            ("sam.torres", "This is the third memory event this month. Ticket filed for permanent fix."),
            ("alex.chen", "Heap dump attached to Jira PLAT-4421. Root cause: unclosed Redis connections in token validator."),
            ("ops.bot", "Auto-remediation: pod restarted, connections drained before restart."),
        ],
    },
    {
        "id": "seed-inc-003",
        "title": "p99 latency spike on api-gateway exceeding 2000ms",
        "severity": "sev1", "status": "active", "service": "api-gateway",
        "region": "us-east-1", "env": "prod", "auto_healed": False,
        "duration_min": None, "days_ago": 0,
        "annotations": [
            ("priya.k", "Investigating upstream — search-service dependency showing high connection wait times."),
        ],
    },
    {
        "id": "seed-inc-004",
        "title": "Data pipeline job failure — 3 consecutive missed runs",
        "severity": "sev2", "status": "resolved", "service": "data-pipeline",
        "region": "us-west-2", "env": "prod", "auto_healed": False,
        "duration_min": 95, "days_ago": 8,
        "annotations": [
            ("jen.wu", "S3 permissions revoked during IAM rotation. Fixed manually."),
            ("sam.torres", "Added automated IAM health check to prevent recurrence."),
        ],
    },
    {
        "id": "seed-inc-005",
        "title": "Disk utilization at 94% on search-service nodes",
        "severity": "sev2", "status": "active", "service": "search-service",
        "region": "eu-west-1", "env": "prod", "auto_healed": False,
        "duration_min": None, "days_ago": 0,
        "annotations": [
            ("ops.bot", "Automated cleanup of old index segments initiated — requires manual review before purge."),
        ],
    },
    {
        "id": "seed-inc-006",
        "title": "notification-service: queue depth exceeded 50k messages",
        "severity": "sev2", "status": "escalated", "service": "notification-service",
        "region": "us-east-1", "env": "prod", "auto_healed": False,
        "duration_min": 180, "days_ago": 3,
        "annotations": [
            ("alex.chen", "Queue consumer crashed — on-call paged via PagerDuty at 02:14 UTC."),
            ("priya.k", "Root cause: Redis OOM causing consumer group lag. Scaled Redis cluster."),
            ("jen.wu", "Messages processed. Backlog cleared at 05:47 UTC."),
        ],
    },
    {
        "id": "seed-inc-007",
        "title": "Elevated CPU on recommendation-engine — sustained above 85%",
        "severity": "sev2", "status": "resolved", "service": "recommendation-engine",
        "region": "us-west-2", "env": "prod", "auto_healed": True,
        "duration_min": 18, "days_ago": 12,
    },
    {
        "id": "seed-inc-008",
        "title": "user-profile service returning 503 intermittently in us-east-1",
        "severity": "sev1", "status": "resolved", "service": "user-profile",
        "region": "us-east-1", "env": "prod", "auto_healed": True,
        "duration_min": 9, "days_ago": 15,
    },
    {
        "id": "seed-inc-009",
        "title": "inventory-service connection pool exhausted — DB write failures",
        "severity": "sev2", "status": "resolved", "service": "inventory-service",
        "region": "us-east-1", "env": "prod", "auto_healed": True,
        "duration_min": 14, "days_ago": 18,
    },
    {
        "id": "seed-inc-010",
        "title": "Slow queries on payment-processor DB replica — p50 >800ms",
        "severity": "sev3", "status": "resolved", "service": "payment-processor",
        "region": "eu-west-1", "env": "prod", "auto_healed": False,
        "duration_min": 240, "days_ago": 20,
        "annotations": [
            ("sam.torres", "EXPLAIN ANALYZE shows missing index on transactions.created_at. Index added."),
        ],
    },
    {
        "id": "seed-inc-011",
        "title": "search-service index replication lag exceeding 45 seconds",
        "severity": "sev3", "status": "active", "service": "search-service",
        "region": "us-west-2", "env": "prod", "auto_healed": False,
        "duration_min": None, "days_ago": 1,
    },
    {
        "id": "seed-inc-012",
        "title": "data-pipeline: S3 export job — AccessDenied on prod bucket",
        "severity": "sev3", "status": "escalated", "service": "data-pipeline",
        "region": "us-east-1", "env": "prod", "auto_healed": False,
        "duration_min": 65, "days_ago": 6,
    },
    {
        "id": "seed-inc-013",
        "title": "auth-service: JWT validation failure rate 2.1x above baseline",
        "severity": "sev1", "status": "resolved", "service": "auth-service",
        "region": "us-west-2", "env": "prod", "auto_healed": True,
        "duration_min": 6, "days_ago": 22,
    },
    {
        "id": "seed-inc-014",
        "title": "checkout-service: Redis connection refused — cart operations failing",
        "severity": "sev2", "status": "resolved", "service": "checkout-service",
        "region": "us-east-1", "env": "prod", "auto_healed": True,
        "duration_min": 11, "days_ago": 25,
    },
    {
        "id": "seed-inc-015",
        "title": "api-gateway: TLS certificate expiry in 7 days — staging",
        "severity": "sev4", "status": "resolved", "service": "api-gateway",
        "region": "us-east-1", "env": "staging", "auto_healed": False,
        "duration_min": 30, "days_ago": 28,
    },
]

POSTMORTEM_INCIDENTS = ["seed-inc-001", "seed-inc-002", "seed-inc-006", "seed-inc-008", "seed-inc-009"]

INTEGRATIONS_SPECS = [
    {"name": "Jira",        "type": "jira",        "status": "connected",    "lag_min": 5},
    {"name": "Slack",       "type": "slack",        "status": "connected",    "lag_min": 1},
    {"name": "PagerDuty",   "type": "pagerduty",    "status": "connected",    "lag_min": 10},
    {"name": "Prometheus",  "type": "prometheus",   "status": "connected",    "lag_min": 0},
    {"name": "Datadog",     "type": "datadog",      "status": "disconnected", "lag_min": None},
    {"name": "CloudWatch",  "type": "cloudwatch",   "status": "connected",    "lag_min": 2},
]

CLUSTER_SPECS = [
    {
        "name": "prod-us-east-1", "region": "us-east-1", "env": "prod",
        "status": "healthy", "nodes": 24, "ns": 18, "pods": 180,
        "bad": [
            {"pod": "payment-processor-6d8b4-xt9p2", "namespace": "payments",  "status": "CrashLoopBackOff", "restarts": 8,  "node": "ip-10-0-1-42.ec2.internal",  "age": "3h 12m", "cpu": "0m",    "memory": "48Mi"},
            {"pod": "notification-svc-worker-5f7c3",  "namespace": "messaging", "status": "OOMKilled",        "restarts": 3,  "node": "ip-10-0-1-87.ec2.internal",  "age": "1h 44m", "cpu": "12m",   "memory": "512Mi"},
        ],
    },
    {
        "name": "prod-us-west-2", "region": "us-west-2", "env": "prod",
        "status": "healthy", "nodes": 18, "ns": 14, "pods": 142,
        "bad": [
            {"pod": "recommendation-engine-7b9d2-kp4r", "namespace": "ml",      "status": "Pending",          "restarts": 0,  "node": "ip-10-1-2-33.ec2.internal",  "age": "22m",    "cpu": "0m",    "memory": "0Mi"},
            {"pod": "auth-service-5c6f8-mq7n1",          "namespace": "auth",    "status": "CrashLoopBackOff", "restarts": 5,  "node": "ip-10-1-2-61.ec2.internal",  "age": "55m",    "cpu": "0m",    "memory": "32Mi"},
        ],
    },
    {
        "name": "prod-eu-west-1", "region": "eu-west-1", "env": "prod",
        "status": "degraded", "nodes": 12, "ns": 10, "pods": 98,
        "bad": [
            {"pod": "search-service-7d9f4-xk2p1",  "namespace": "search",   "status": "CrashLoopBackOff", "restarts": 14, "node": "ip-172-16-3-12.eu-west-1.compute.internal", "age": "6h 8m",  "cpu": "0m",   "memory": "128Mi"},
            {"pod": "search-service-7d9f4-nm8r3",  "namespace": "search",   "status": "OOMKilled",        "restarts": 7,  "node": "ip-172-16-3-19.eu-west-1.compute.internal", "age": "6h 8m",  "cpu": "4m",   "memory": "512Mi"},
            {"pod": "data-pipeline-cron-28491",    "namespace": "batch",    "status": "ImagePullBackOff", "restarts": 0,  "node": "ip-172-16-3-44.eu-west-1.compute.internal", "age": "14m",    "cpu": "0m",   "memory": "0Mi"},
            {"pod": "inventory-service-8e2a1-rv6t","namespace": "commerce", "status": "Evicted",          "restarts": 0,  "node": "ip-172-16-3-12.eu-west-1.compute.internal", "age": "2h 31m", "cpu": "0m",   "memory": "0Mi"},
            {"pod": "checkout-redis-0",             "namespace": "commerce", "status": "Pending",          "restarts": 0,  "node": "",                                          "age": "8m",     "cpu": "0m",   "memory": "0Mi"},
        ],
    },
    {
        "name": "staging-us-east-1", "region": "us-east-1", "env": "staging",
        "status": "healthy", "nodes": 6, "ns": 8, "pods": 45,
        "bad": [
            {"pod": "api-gateway-canary-9f3b2-jw8k", "namespace": "gateway", "status": "CrashLoopBackOff", "restarts": 2, "node": "ip-10-0-3-5.ec2.internal", "age": "18m", "cpu": "0m", "memory": "16Mi"},
        ],
    },
    {
        "name": "dev-us-east-1", "region": "us-east-1", "env": "dev",
        "status": "healthy", "nodes": 4, "ns": 5, "pods": 28,
        "bad": [],
    },
]

METRICS = [
    ("cpu_utilization",    0.0,  1.0,   0.82, 0.06),
    ("memory_utilization", 0.0,  1.0,   0.70, 0.12),
    ("error_rate",         0.0,  0.5,   0.02, 0.02),
    ("latency_p99_ms",     10.0, 5000.0,400.0, 300.0),
    ("disk_utilization",   0.0,  1.0,   0.65, 0.10),
    ("request_rate_rps",   5.0,  2000.0,400.0, 200.0),
    ("connection_pool_pct",0.0,  1.0,   0.60, 0.15),
    ("gc_pause_ms",        0.0,  500.0, 40.0, 30.0),
]

NEAR_MISS_SPECS = [
    ("api-gateway",          "us-east-1", "cpu_utilization",    0.94, 0.95, 1.1),
    ("payment-processor",    "us-east-1", "error_rate",         0.048, 0.05, 4.0),
    ("auth-service",         "us-east-1", "memory_utilization", 0.93, 0.95, 2.1),
    ("search-service",       "eu-west-1", "disk_utilization",   0.929, 0.94, 1.2),
    ("recommendation-engine","us-west-2", "cpu_utilization",    0.91, 0.95, 4.2),
    ("notification-service", "us-east-1", "connection_pool_pct",0.97, 0.98, 1.0),
    ("data-pipeline",        "us-west-2", "memory_utilization", 0.878, 0.90, 2.4),
    ("inventory-service",    "us-east-1", "error_rate",         0.038, 0.04, 5.0),
    ("checkout-service",     "us-east-1", "latency_p99_ms",     1850.0, 2000.0, 7.5),
    ("user-profile",         "us-east-1", "cpu_utilization",    0.906, 0.95, 4.6),
    ("api-gateway",          "us-west-2", "connection_pool_pct",0.924, 0.95, 2.7),
    ("auth-service",         "eu-west-1", "error_rate",         0.019, 0.02, 5.0),
    ("search-service",       "us-east-1", "disk_utilization",   0.908, 0.94, 3.4),
    ("payment-processor",    "eu-west-1", "latency_p99_ms",     1920.0, 2000.0, 4.0),
    ("data-pipeline",        "us-east-1", "cpu_utilization",    0.917, 0.95, 3.5),
]

RECOMMENDATION_SPECS = [
    ("auth-service",          "pod_restart",         0.94, "pod_restart resolves auth-service OOM events in 94% of cases — consider auto-approving for sev2+."),
    ("payment-processor",     "rollout_restart",     0.91, "payment-processor error spikes correlate with deploy events — rollout restart after deploy gate suppresses 91% of incidents."),
    ("notification-service",  "scale_up",            0.87, "notification-service queue depth breaches resolve after scaling to 3 replicas — add to auto-scale policy."),
    ("search-service",        "cache_flush",         0.83, "search-service index lag incidents clear after coordinated cache flush — 83% success rate over last 30 days."),
    ("api-gateway",           "circuit_breaker_open",0.78, "api-gateway latency spikes are downstream from search-service — opening circuit breaker prevents cascade in 78% of cases."),
    ("recommendation-engine", "pod_restart",         0.88, "recommendation-engine CPU saturations self-clear after pod restart — 88% success, avg resolution 4.2 min."),
    ("checkout-service",      "alert_suppress",      0.72, "checkout-service Redis hiccups self-resolve within 90 seconds — alert suppression window would reduce noise by 72%."),
    ("inventory-service",     "scale_up",            0.85, "inventory-service connection pool exhaustion resolves with +2 replicas — 85% success, consider adding to auto-scale trigger."),
    ("data-pipeline",         "runbook_execute",     0.69, "data-pipeline S3 access failures follow IAM rotation cadence — automated token refresh runbook has 69% resolution rate."),
    ("user-profile",          "rollout_restart",     0.90, "user-profile 503 errors are stateless restart-safe — rollout restart resolves in avg 6.1 min at 90% success rate."),
]


# ══════════════════════════════════════════════════════════════════════════════
# TIMELINE FACTORIES
# ══════════════════════════════════════════════════════════════════════════════

def make_timeline_auto_healed(inc: Incident, spec: dict) -> list[dict]:
    svc = spec["service"]
    region = spec["region"]
    t = inc.started_at
    metric = rng.choice(["error_rate", "cpu_utilization", "memory_utilization", "latency_p99_ms"])
    threshold = {"error_rate": "5.0%", "cpu_utilization": "85%",
                 "memory_utilization": "90%", "latency_p99_ms": "1000ms"}[metric]
    observed = {"error_rate": f"{rng.uniform(6, 15):.1f}%",
                "cpu_utilization": f"{rng.randint(87, 98)}%",
                "memory_utilization": f"{rng.uniform(92, 98):.1f}%",
                "latency_p99_ms": f"{rng.randint(1100, 2800)}ms"}[metric]
    action_cmd = rng.choice([
        f"kubectl rollout restart deployment/{svc}-v2 -n {rng.choice(['default','prod','services'])}",
        f"kubectl delete pod -l app={svc} --field-selector=status.phase=Running",
        f"helm upgrade {svc} ./charts/{svc} --reuse-values --set replicas={rng.randint(2,4)}",
    ])
    baseline = {"error_rate": f"{rng.uniform(0.2, 0.8):.1f}%",
                "cpu_utilization": f"{rng.randint(30, 55)}%",
                "memory_utilization": f"{rng.uniform(55, 72):.1f}%",
                "latency_p99_ms": f"{rng.randint(80, 350)}ms"}[metric]
    dur = inc.duration_seconds or 420

    events = [
        {"dt": t,                       "type": "anomaly.detected",   "actor": "cortex",  "sev": "warning",
         "desc": f"Anomaly detected: {metric}={observed} exceeds threshold {threshold} on {svc} ({region}).",
         "meta": {"metric": metric, "value": observed, "threshold": threshold}},
        {"dt": t + timedelta(seconds=15),"type": "insight.analyzed",  "actor": "cortex",  "sev": "info",
         "desc": f"Cortex Insight: pattern matched — transient {metric} spike on {svc}. Similar pattern resolved via pod restart in previous 8 incidents.",
         "meta": {"confidence": round(rng.uniform(0.80, 0.96), 2), "similar_incidents": rng.randint(5, 12)}},
        {"dt": t + timedelta(seconds=28),"type": "decision.created",  "actor": "cortex",  "sev": "info",
         "desc": f"Decision: auto-mitigation approved — pod restart recommended (policy: sev{spec['severity'][-1]}-auto-heal).",
         "meta": {"action": "pod_restart", "policy": f"sev{spec['severity'][-1]}-auto-heal"}},
        {"dt": t + timedelta(seconds=35),"type": "action.executed",   "actor": "cortex",  "sev": "info",
         "desc": f"Action executed: {action_cmd}",
         "meta": {"command": action_cmd, "namespace": "prod"}},
        {"dt": t + timedelta(seconds=dur - 90), "type": "verify.checking", "actor": "cortex", "sev": "info",
         "desc": f"Verification: monitoring {metric} post-restart. Current: {rng.choice(['trending down', 'stabilising'])}.",
         "meta": {"checks": 3, "interval_seconds": 30}},
        {"dt": t + timedelta(seconds=dur - 15), "type": "verify.passed",   "actor": "cortex", "sev": "info",
         "desc": f"Verification passed: {metric} returned to {baseline} — within baseline. SLO impact: minimal.",
         "meta": {"metric": metric, "restored_value": baseline}},
        {"dt": t + timedelta(seconds=dur),      "type": "incident.resolved","actor": "cortex","sev": "info",
         "desc": f"Incident auto-resolved by Cortex after {dur // 60}m {dur % 60}s. No human intervention required.",
         "meta": {"resolution_type": "auto_healed", "duration_seconds": dur}},
    ]
    return events


def make_timeline_manual(inc: Incident, spec: dict) -> list[dict]:
    svc = spec["service"]
    region = spec["region"]
    t = inc.started_at
    dur = inc.duration_seconds or 3600

    events = [
        {"dt": t,                           "type": "anomaly.detected",    "actor": "cortex",   "sev": "critical",
         "desc": f"Critical anomaly on {svc} ({region}) — degraded state detected across multiple metrics.",
         "meta": {"service": svc}},
        {"dt": t + timedelta(seconds=20),   "type": "insight.analyzed",    "actor": "cortex",   "sev": "info",
         "desc": f"Cortex Insight: no high-confidence automated remediation available. Escalating to on-call.",
         "meta": {"confidence": round(rng.uniform(0.40, 0.65), 2)}},
        {"dt": t + timedelta(seconds=35),   "type": "escalation.pagerduty","actor": "cortex",   "sev": "warning",
         "desc": f"On-call engineer paged via PagerDuty — incident {inc.id[:8]} (sev{spec['severity'][-1]}).",
         "meta": {"channel": "pagerduty", "policy": "on-call-rotation"}},
        {"dt": t + timedelta(seconds=40),   "type": "escalation.slack",    "actor": "cortex",   "sev": "info",
         "desc": f"Alert posted to #incidents-prod with runbook link. Severity: {spec['severity']}.",
         "meta": {"channel": "#incidents-prod", "runbook": f"https://runbooks.internal/{svc}/troubleshoot"}},
        {"dt": t + timedelta(seconds=210),  "type": "human.acknowledged",  "actor": "human",    "sev": "info",
         "desc": f"Incident acknowledged by on-call engineer. Investigation started.",
         "meta": {"actor_role": "oncall-sre"}},
        {"dt": t + timedelta(seconds=dur - 120),"type": "action.executed", "actor": "human",    "sev": "info",
         "desc": f"Manual remediation applied by on-call engineer.",
         "meta": {"manual": True}},
        {"dt": t + timedelta(seconds=dur),  "type": "incident.resolved",   "actor": "human",    "sev": "info",
         "desc": f"Incident resolved by on-call engineer after {dur // 60}m {dur % 60}s.",
         "meta": {"resolution_type": "manual", "duration_seconds": dur}},
    ]
    return events


def make_timeline_escalated(inc: Incident, spec: dict) -> list[dict]:
    svc = spec["service"]
    t = inc.started_at

    events = [
        {"dt": t,                          "type": "anomaly.detected",    "actor": "cortex", "sev": "critical",
         "desc": f"Multi-metric anomaly on {svc} — sustained degradation exceeds auto-heal confidence threshold.",
         "meta": {"service": svc}},
        {"dt": t + timedelta(seconds=18),  "type": "insight.analyzed",    "actor": "cortex", "sev": "info",
         "desc": "Insight: pattern partially matched but confidence below 70% — human oversight required.",
         "meta": {"confidence": round(rng.uniform(0.45, 0.68), 2)}},
        {"dt": t + timedelta(seconds=30),  "type": "decision.created",    "actor": "cortex", "sev": "warning",
         "desc": "Decision: attempting limited auto-mitigation then escalating regardless of outcome.",
         "meta": {"action": "pod_restart", "escalate_after": True}},
        {"dt": t + timedelta(seconds=45),  "type": "action.executed",     "actor": "cortex", "sev": "info",
         "desc": f"Action executed: kubectl rollout restart deployment/{svc}",
         "meta": {}},
        {"dt": t + timedelta(seconds=180), "type": "verify.failed",       "actor": "cortex", "sev": "warning",
         "desc": f"{svc} still degraded after restart. Escalating to on-call.",
         "meta": {"attempt": 1, "outcome": "degraded_persists"}},
        {"dt": t + timedelta(seconds=195), "type": "escalation.pagerduty","actor": "cortex", "sev": "critical",
         "desc": "Escalated: on-call paged. Cortex handing off to human responder.",
         "meta": {"channel": "pagerduty"}},
        {"dt": t + timedelta(minutes=12),  "type": "human.acknowledged",  "actor": "human",  "sev": "info",
         "desc": "On-call engineer acknowledged. Investigating root cause.",
         "meta": {"actor_role": "oncall-sre"}},
    ]
    return events


def make_timeline_active(inc: Incident, spec: dict) -> list[dict]:
    svc = spec["service"]
    t = inc.started_at

    events = [
        {"dt": t,                          "type": "anomaly.detected",    "actor": "cortex", "sev": "critical",
         "desc": f"Anomaly detected on {svc} — conditions for auto-heal not met.",
         "meta": {"service": svc}},
        {"dt": t + timedelta(seconds=22),  "type": "insight.analyzed",    "actor": "cortex", "sev": "info",
         "desc": "Insight: novel pattern — no historical match above 60% confidence. Escalating to on-call.",
         "meta": {"confidence": round(rng.uniform(0.35, 0.59), 2)}},
        {"dt": t + timedelta(seconds=40),  "type": "escalation.pagerduty","actor": "cortex", "sev": "warning",
         "desc": "On-call paged. Cortex continuing to monitor and collect telemetry.",
         "meta": {"monitoring": True}},
        {"dt": t + timedelta(minutes=8),   "type": "human.acknowledged",  "actor": "human",  "sev": "info",
         "desc": "On-call acknowledged. Active investigation in progress.",
         "meta": {"actor_role": "oncall-sre"}},
    ]
    return events


def make_timeline(inc: Incident, spec: dict) -> list[dict]:
    status = spec["status"]
    if status == "resolved" and spec.get("auto_healed"):
        return make_timeline_auto_healed(inc, spec)
    elif status == "resolved":
        return make_timeline_manual(inc, spec)
    elif status == "escalated":
        return make_timeline_escalated(inc, spec)
    else:  # active
        return make_timeline_active(inc, spec)


# ══════════════════════════════════════════════════════════════════════════════
# POSTMORTEM FACTORY
# ══════════════════════════════════════════════════════════════════════════════

POSTMORTEM_TEMPLATES = {
    "seed-inc-001": ("alex.chen", """
## Summary
A deployment of payment-processor v2.4.1 at 14:20 UTC introduced a regression in the error handling path, causing error rates to spike from 0.3% to 8.3% within 2 minutes. Cortex detected the anomaly, approved auto-mitigation, and executed a rollout restart that resolved the incident in 7 minutes with no SLO breach.

## Timeline
- **14:20 UTC** — payment-processor v2.4.1 deployed to prod-us-east-1
- **14:22 UTC** — Error rate crosses 5% threshold; Cortex anomaly detection fires
- **14:23 UTC** — Cortex executes rollout restart (confidence: 94%)
- **14:29 UTC** — Error rate returns to 0.4%; incident auto-resolved

## Root Cause
A null-pointer dereference in the new retry logic in v2.4.1. The error occurred when upstream payment gateway returned HTTP 202 (previously only 200 was handled). The regression was not caught in staging because the integration test suite mocked the gateway response.

## Impact
- **Duration:** 7 minutes
- **Error rate peak:** 8.3% (baseline: 0.3%)
- **Transactions affected:** ~1,400 failed payment attempts
- **Revenue impact:** Estimated $12K in failed transactions (all retried successfully by clients)
- **SLO impact:** None — 99.95% availability maintained for the month

## What Went Well
- Cortex detected the anomaly within 2 minutes of deployment
- Auto-heal resolved the incident without human intervention
- Rollback was clean and fast (no data corruption)

## What Went Wrong
- Integration test suite used mocked gateway responses — didn't catch the HTTP 202 case
- Deployment was not staged (went directly to 100% of traffic)

## Action Items
- [ ] Fix integration tests to include HTTP 202 gateway response path (owner: @alex.chen, due: this sprint)
- [ ] Enable canary deploys for payment-processor (owner: @platform-team, due: next quarter)
- [ ] Add HTTP 202 handling to payment gateway client library (owner: @payments-team, due: this sprint)
"""),
    "seed-inc-002": ("sam.torres", """
## Summary
A memory leak in the auth-service token validator caused progressive memory growth over 6 hours, resulting in OOM kills on 2 of 4 pods. Cortex detected the event, restarted the affected pods with connection draining, and resolved the incident in 12 minutes. Root cause: unclosed Redis connections in the JWT validation path.

## Timeline
- **08:14 UTC** — auth-service memory begins gradual growth (normal churn: 512MB → climbing)
- **09:30 UTC** — Memory at 1.8GB on pod auth-service-7c8d4-kp1n2; Redis connection count: 847
- **10:48 UTC** — OOM kill on auth-service-7c8d4-kp1n2 (RSS 2.1GB)
- **10:49 UTC** — Cortex detects memory anomaly pattern, approves pod restart with drain
- **11:01 UTC** — All pods restarted, memory stabilised at 612MB

## Root Cause
The JWT validator introduced in v3.8.2 opens a Redis connection per validation call to check token revocation status, but does not properly return connections to the pool under error conditions. Under normal load, the leak is slow (~50 connections/hour). Under sustained traffic, it accelerates to OOM within 6 hours.

## Impact
- **Duration:** 12 minutes (Cortex response time) + 6 hours latent leak
- **Auth failures:** 0 — pod restart was staggered with connection draining
- **User impact:** None detected — healthy pods served traffic during restart

## What Went Well
- Cortex pattern-matched the OOM signature from a previous incident and executed drain-first restart
- Zero user-facing auth failures despite pod OOM
- Heap dump automatically captured and attached to Jira ticket

## What Went Wrong
- Redis connection pooling was not validated in code review for v3.8.2
- No memory growth alert existed — relied on OOM event detection

## Action Items
- [ ] Fix Redis connection pool return in JWT validator error paths (owner: @auth-team, due: hotfix)
- [ ] Add Redis connection count metric alert (threshold: >500/pod) (owner: @sam.torres, due: this week)
- [ ] Add memory growth rate alert (>100MB/hour sustained) (owner: @ops-team, due: this sprint)
"""),
    "seed-inc-006": ("priya.k", """
## Summary
A consumer group crash in notification-service caused queue depth to grow to 73,000 messages over 3 hours. The root cause was Redis OOM on the shared cache cluster. On-call was paged at 02:14 UTC and resolved the backlog by scaling Redis and restarting consumers. Total duration: 3 hours.

## Timeline
- **23:48 UTC** — Redis memory utilization crosses 85% on shared-cache-prod-1
- **00:12 UTC** — notification-service consumer group pauses (Redis ENOMEM on message acknowledgement)
- **02:14 UTC** — Queue depth reaches 50k threshold; Cortex pages on-call via PagerDuty
- **02:28 UTC** — On-call engineer acknowledges
- **03:15 UTC** — Redis cluster scaled from 3→5 nodes; consumers restarted
- **05:47 UTC** — Backlog cleared; all notifications delivered

## Root Cause
Redis memory exhaustion due to unbounded TTL-less cache keys set by a recent release of the recommendations engine. The shared-cache cluster was not adequately sized for the new write pattern.

## Impact
- **Duration:** 3 hours 47 minutes
- **Messages delayed:** 73,000 push notifications
- **User impact:** Delayed notifications (no user data loss)
- **SLO breach:** Yes — notification delivery SLO requires <5 min delivery. Breach window: 3h 47m

## What Went Well
- Queue durability meant no message loss despite consumer crash
- On-call responded within 14 minutes of page

## What Went Wrong
- Shared Redis cluster — recommendations engine cache growth impacted unrelated service
- No per-service Redis quota enforcement
- No memory growth alerting on shared-cache cluster

## Action Items
- [ ] Isolate notification-service onto dedicated Redis cluster (owner: @platform-team, due: Q3)
- [ ] Enforce Redis key TTL policy for shared cache (owner: @sam.torres, due: this week)
- [ ] Add Redis memory growth alert at 75% (owner: @ops-team, due: this sprint)
- [ ] Review recommendations engine cache strategy (owner: @reco-team, due: next sprint)
"""),
    "seed-inc-008": ("jen.wu", """
## Summary
A transient network partition caused user-profile pods to fail health checks and return 503s intermittently. Cortex detected the degraded state within 60 seconds, executed a rolling restart with traffic draining, and restored service in 9 minutes.

## Timeline
- **16:32 UTC** — Network partition event on subnet prod-us-east-1-priv-1a (AWS AZ issue)
- **16:33 UTC** — user-profile health check failure rate spikes to 34%
- **16:34 UTC** — Cortex detects 503 pattern; initiates rolling restart
- **16:43 UTC** — All pods healthy; 503 rate returns to 0%

## Root Cause
AWS us-east-1 AZ degradation event affecting the private subnet. Pods lost connectivity to the PostgreSQL read replica briefly, causing health check failures. The restart rebalanced pods across AZs, avoiding the degraded AZ.

## Impact
- **Duration:** 9 minutes
- **Error rate peak:** 34% intermittent 503s
- **User impact:** ~2,100 profile load failures (all client-retried)
- **SLO:** Maintained — degradation was below breach threshold

## What Went Well
- Sub-60-second detection and automated remediation
- Rolling restart avoided service interruption during recovery

## What Went Wrong
- Pods were over-concentrated in a single AZ (pod anti-affinity rules not enforced)

## Action Items
- [ ] Enforce pod anti-affinity for user-profile across AZs (owner: @platform-team, due: this sprint)
- [ ] Review AZ spread for all stateless services (owner: @infra-team, due: next sprint)
"""),
    "seed-inc-009": ("sam.torres", """
## Summary
A surge in write traffic (3.2x baseline) exhausted the connection pool on inventory-service's PostgreSQL primary, causing write failures. Cortex detected the pool exhaustion pattern, scaled the service horizontally (+2 replicas), and restored normal operations in 14 minutes.

## Timeline
- **11:02 UTC** — Flash sale campaign launches; write traffic spikes to 3.2x baseline
- **11:04 UTC** — Connection pool at 98%; writes begin failing (JDBC pool timeout)
- **11:05 UTC** — Cortex detects connection pool exhaustion signature
- **11:06 UTC** — Cortex scales inventory-service to 5 replicas (from 3)
- **11:19 UTC** — Pool utilization normalises at 45%; write failures cease

## Root Cause
The connection pool size was statically configured at 50 connections shared across 3 replicas. The flash sale campaign was not communicated to the platform team, so no pre-scaling was performed.

## Impact
- **Duration:** 14 minutes
- **Write failures:** ~4,200 inventory update failures
- **User impact:** ~800 orders showed stale inventory (all corrected within 10 minutes)

## What Went Well
- Cortex auto-scaled without human intervention
- No orders were lost — failures were queued and replayed

## What Went Wrong
- Flash sale was not in the ops calendar — no capacity pre-warning
- Static connection pool configuration not reviewed since initial deployment

## Action Items
- [ ] Implement dynamic connection pool scaling based on replica count (owner: @inventory-team, due: next sprint)
- [ ] Add flash sale / marketing event to ops calendar (owner: @ops-team, ongoing)
- [ ] Add connection pool utilization alert at 80% (owner: @sam.torres, due: this week)
"""),
}


# ══════════════════════════════════════════════════════════════════════════════
# SEEDER
# ══════════════════════════════════════════════════════════════════════════════

def _now_minus(days: float, hours: float = 0, minutes: float = 0) -> datetime:
    return datetime.utcnow() - timedelta(days=days, hours=hours, minutes=minutes)


def seed_all(db, *, reset: bool = False) -> None:
    if reset:
        print("  → Clearing existing seeded data…")
        # Delete in FK-safe order
        for Model in [TimelineEvent, Annotation, Postmortem, Action, Incident,
                      Signal, LearnOutcome, Recommendation, Integration,
                      ClusterInventory, PullerRun, NearMiss, ServiceEdgeMetric]:
            db.query(Model).delete()
        db.commit()
        print("  → Cleared.")

    _seed_incidents(db)
    _seed_signals(db)
    _seed_actions(db)
    _seed_learn_outcomes(db)
    _seed_recommendations(db)
    _seed_integrations(db)
    _seed_clusters(db)
    _seed_puller_runs(db)
    _seed_near_misses(db)
    _seed_golden_signals(db)
    db.commit()


def _seed_incidents(db) -> None:
    print("  → Seeding incidents, timelines, annotations, postmortems…")
    for spec in INCIDENT_SPECS:
        if db.get(Incident, spec["id"]):
            continue  # already seeded

        start = _now_minus(spec["days_ago"])
        dur_s = spec["duration_min"] * 60 if spec["duration_min"] else None
        resolved_at = (start + timedelta(seconds=dur_s)) if dur_s else None

        inc = Incident(
            id=spec["id"],
            title=spec["title"],
            severity=spec["severity"],
            status=spec["status"],
            service=spec["service"],
            region=spec["region"],
            environment=spec.get("env", "prod"),
            org_id="default",
            started_at=start,
            resolved_at=resolved_at,
            duration_seconds=dur_s,
            auto_healed=spec.get("auto_healed", False),
            mttr_seconds=dur_s,
            created_at=start,
            updated_at=resolved_at or start,
        )
        db.add(inc)
        db.flush()

        # Timeline
        for ev in make_timeline(inc, spec):
            db.add(TimelineEvent(
                id=str(uuid4()),
                incident_id=inc.id,
                event_type=ev["type"],
                description=ev["desc"],
                actor=ev["actor"],
                severity=ev["sev"],
                timestamp=ev["dt"],
                metadata_=ev.get("meta"),
            ))

        # Annotations
        for author, content in spec.get("annotations", []):
            offset_min = rng.randint(5, 60)
            db.add(Annotation(
                id=str(uuid4()),
                incident_id=inc.id,
                author=author,
                content=content,
                created_at=start + timedelta(minutes=offset_min),
            ))

        # Postmortem
        if spec["id"] in POSTMORTEM_INCIDENTS and spec["id"] in POSTMORTEM_TEMPLATES:
            author, content = POSTMORTEM_TEMPLATES[spec["id"]]
            db.add(Postmortem(
                id=str(uuid4()),
                incident_id=inc.id,
                content=textwrap.dedent(content).strip(),
                author=author,
                created_at=start + timedelta(hours=rng.randint(2, 8)),
                updated_at=start + timedelta(hours=rng.randint(10, 24)),
            ))

    print(f"     {len(INCIDENT_SPECS)} incidents")


def _seed_signals(db) -> None:
    print("  → Seeding 500 signals…")
    count = 0
    for service in SERVICES:
        region = rng.choice(REGIONS)
        for metric_name, lo, hi, mu, sigma in METRICS:
            # ~6 signals per service+metric over 7 days = ~480 total
            n = rng.randint(4, 8)
            for _ in range(n):
                days_back = rng.uniform(0, 7)
                val = min(hi, max(lo, rng.gauss(mu, sigma)))
                # Occasional spike
                if rng.random() < 0.08:
                    val = min(hi, mu + sigma * rng.uniform(3, 6))
                sev = "critical" if val > mu + 3 * sigma else \
                      "warning"  if val > mu + 1.5 * sigma else "info"
                db.add(Signal(
                    id=str(uuid4()),
                    source="prometheus",
                    metric_name=metric_name,
                    value=round(val, 4),
                    severity=sev,
                    service=service,
                    region=region,
                    environment="prod",
                    org_id="default",
                    timestamp=_now_minus(days_back),
                    raw_payload={"metric": metric_name, "value": val, "service": service},
                ))
                count += 1
    print(f"     {count} signals")


def _seed_actions(db) -> None:
    print("  → Seeding actions…")
    action_types = ["pod_restart", "rollout_restart", "scale_up", "cache_flush",
                    "circuit_breaker_open", "alert_suppress", "runbook_execute"]
    statuses = ["success"] * 7 + ["failed"] * 2 + ["skipped"]
    inc_ids = [spec["id"] for spec in INCIDENT_SPECS]
    for i in range(20):
        inc_id = rng.choice(inc_ids)
        at = rng.choice(action_types)
        svc = rng.choice(SERVICES)
        db.add(Action(
            id=str(uuid4()),
            incident_id=inc_id,
            action_type=at,
            status=rng.choice(statuses),
            target=f"{svc}/prod-{rng.choice(['us-east-1','us-west-2'])}",
            parameters={"namespace": "prod", "replicas": rng.randint(2, 5)},
            executed_at=_now_minus(rng.uniform(0, 30)),
            result={"exit_code": 0, "duration_ms": rng.randint(200, 8000)},
        ))
    print("     20 actions")


def _seed_learn_outcomes(db) -> None:
    print("  → Seeding 30 learn outcomes…")
    action_types = ["pod_restart", "rollout_restart", "scale_up", "cache_flush",
                    "circuit_breaker_open", "alert_suppress", "runbook_execute"]
    outcomes = ["success"] * 8 + ["failed"] * 2
    for i in range(30):
        svc = rng.choice(SERVICES)
        at = rng.choice(action_types)
        outcome = rng.choice(outcomes)
        db.add(LearnOutcome(
            id=str(uuid4()),
            incident_id=rng.choice([spec["id"] for spec in INCIDENT_SPECS]),
            action_type=at,
            service=svc,
            severity=rng.choice(["sev1", "sev2", "sev3"]),
            outcome=outcome,
            confidence_delta=round(rng.uniform(0.02, 0.08) if outcome == "success" else -0.03, 3),
            recorded_at=_now_minus(rng.uniform(0, 60)),
        ))
    print("     30 outcomes")


def _seed_recommendations(db) -> None:
    print("  → Seeding 10 recommendations…")
    for svc, action, conf, rationale in RECOMMENDATION_SPECS:
        existing = db.query(Recommendation).filter_by(service=svc, action_type=action).first()
        if existing:
            continue
        db.add(Recommendation(
            id=str(uuid4()),
            service=svc,
            action_type=action,
            confidence=conf,
            rationale=rationale,
            status="pending",
            created_at=_now_minus(rng.uniform(1, 10)),
        ))
    print("     10 recommendations")


def _seed_integrations(db) -> None:
    print("  → Seeding 6 integrations…")
    for spec in INTEGRATIONS_SPECS:
        if db.query(Integration).filter_by(name=spec["name"]).first():
            continue
        last_sync = (_now_minus(0, minutes=spec["lag_min"]) if spec["lag_min"] is not None else None)
        db.add(Integration(
            id=str(uuid4()),
            name=spec["name"],
            type=spec["type"],
            status=spec["status"],
            config={"url": f"https://{spec['type']}.internal", "auth": "token"},
            last_synced_at=last_sync,
            created_at=_now_minus(rng.randint(30, 180)),
        ))
    print("     6 integrations")


def _seed_clusters(db) -> None:
    print("  → Seeding 5 clusters…")
    for spec in CLUSTER_SPECS:
        if db.query(ClusterInventory).filter_by(cluster_name=spec["name"]).first():
            continue
        db.add(ClusterInventory(
            id=str(uuid4()),
            cluster_name=spec["name"],
            region=spec["region"],
            environment=spec["env"],
            status=spec["status"],
            node_count=spec["nodes"],
            namespace_count=spec["ns"],
            pod_count=spec["pods"],
            unhealthy_pods=spec["bad"] if spec["bad"] else None,
            last_checked_at=_now_minus(0, minutes=rng.randint(1, 15)),
        ))
    print("     5 clusters")


def _seed_puller_runs(db) -> None:
    print("  → Seeding 50 puller runs…")
    sources = ["jira", "prometheus", "cloudwatch", "pagerduty"]
    statuses = ["success"] * 8 + ["failed"] + ["partial"]
    count = 0
    for i in range(50):
        src = rng.choice(sources)
        s = rng.choice(statuses)
        start = _now_minus(rng.uniform(0, 7))
        db.add(PullerRun(
            id=str(uuid4()),
            source=src,
            status=s,
            records_pulled=rng.randint(0, 250) if s != "failed" else 0,
            started_at=start,
            completed_at=start + timedelta(seconds=rng.randint(3, 120)),
            error_message=("Connection timeout" if s == "failed" else None),
        ))
        count += 1
    print(f"     {count} puller runs")


def _seed_near_misses(db) -> None:
    print("  → Seeding 15 near misses…")
    for svc, region, metric, peak, thresh, gap in NEAR_MISS_SPECS:
        db.add(NearMiss(
            id=str(uuid4()),
            service=svc,
            region=region,
            metric_name=metric,
            peak_value=peak,
            threshold=thresh,
            gap_percent=gap,
            detected_at=_now_minus(rng.uniform(0, 14)),
        ))
    print("     15 near misses")


def _seed_golden_signals(db) -> None:
    """Seed recent signals and edge metrics so the Golden Signals page has data."""
    print("  → Seeding Golden Signals data…")

    # Service profiles — realistic baseline values for each service
    PROFILES = {
        "api-gateway":           {"latency": (45, 120, 380),  "rps": 1240, "error": 0.003, "cpu": 0.52, "mem": 0.44, "pool": 0.38},
        "user-profile":          {"latency": (15, 42, 110),   "rps": 650,  "error": 0.002, "cpu": 0.28, "mem": 0.47, "pool": 0.41},
        "checkout-service":      {"latency": (38, 110, 290),  "rps": 280,  "error": 0.009, "cpu": 0.48, "mem": 0.54, "pool": 0.68},
        "auth-service":          {"latency": (12, 38, 95),    "rps": 890,  "error": 0.001, "cpu": 0.31, "mem": 0.58, "pool": 0.72},
        "search-service":        {"latency": (32, 88, 240),   "rps": 780,  "error": 0.007, "cpu": 0.78, "mem": 0.85, "pool": 0.62},
        "recommendation-engine": {"latency": (180, 420, 980), "rps": 560,  "error": 0.012, "cpu": 0.84, "mem": 0.76, "pool": 0.45},
        "notification-service":  {"latency": (8, 22, 58),     "rps": 2100, "error": 0.004, "cpu": 0.41, "mem": 0.39, "pool": 0.91},
        "inventory-service":     {"latency": (20, 65, 170),   "rps": 430,  "error": 0.005, "cpu": 0.55, "mem": 0.63, "pool": 0.55},
        "payment-processor":     {"latency": (28, 95, 210),   "rps": 340,  "error": 0.008, "cpu": 0.67, "mem": 0.71, "pool": 0.87},
        # Tier 3 — data stores
        "auth-db":               {"latency": (2, 6, 18),      "rps": 820,  "error": 0.0005,"cpu": 0.38, "mem": 0.65, "pool": 0.58},
        "data-pipeline":         {"latency": (55, 180, 490),  "rps": 120,  "error": 0.021, "cpu": 0.73, "mem": 0.82, "pool": 0.34},
    }

    METRIC_MAP = [
        ("latency_p99_ms",     lambda p: p["latency"][2] * rng.uniform(0.85, 1.25)),
        ("request_rate_rps",   lambda p: p["rps"] * rng.uniform(0.80, 1.20)),
        ("error_rate",         lambda p: p["error"] * rng.uniform(0.70, 1.80)),
        ("cpu_utilization",    lambda p: p["cpu"] * rng.uniform(0.85, 1.10)),
        ("memory_utilization", lambda p: p["mem"] * rng.uniform(0.90, 1.05)),
        ("connection_pool_pct",lambda p: p["pool"] * rng.uniform(0.80, 1.15) * 100),
    ]

    count = 0
    now = datetime.utcnow()

    # Seed signals across the last 2 hours at 1-minute intervals
    # so both the short window (2 min) and fallback windows have data
    for service, profile in PROFILES.items():
        for minutes_ago in range(0, 121, 1):   # every minute for 2 hours
            ts = now - timedelta(minutes=minutes_ago)
            for metric_name, value_fn in METRIC_MAP:
                value = max(0.0, value_fn(profile))
                # Add occasional spikes for realism
                if rng.random() < 0.05:
                    value *= rng.uniform(1.5, 3.0)
                sev = "info"
                if metric_name == "error_rate" and value > 0.05:
                    sev = "critical"
                elif metric_name == "connection_pool_pct" and value > 90:
                    sev = "critical"
                elif metric_name == "connection_pool_pct" and value > 80:
                    sev = "warning"
                db.add(Signal(
                    id=str(uuid4()),
                    source="prometheus",
                    metric_name=metric_name,
                    value=round(value, 4),
                    severity=sev,
                    service=service,
                    region=rng.choice(["us-east-1", "us-west-2", "eu-west-1"]),
                    environment="prod",
                    org_id="default",
                    timestamp=ts,
                    raw_payload={"metric": metric_name, "service": service},
                ))
                count += 1

    # HAProxy timing profiles per destination service
    # Tq=queue, Tc=connect, Tr=backend (from the service's own latency profile)
    # These reflect real-world observations: high Tq = backend saturated
    HAPROXY = {
        "user-profile":          {"tq": 0.2, "tc": 0.5,  "conns_base": 48},
        "checkout-service":      {"tq": 0.4, "tc": 0.7,  "conns_base": 24},
        "auth-service":          {"tq": 0.2, "tc": 0.4,  "conns_base": 72},
        "search-service":        {"tq": 0.3, "tc": 0.5,  "conns_base": 65},
        "recommendation-engine": {"tq": 1.4, "tc": 0.9,  "conns_base": 41},  # high Tq = ML queue
        "notification-service":  {"tq": 0.1, "tc": 0.3,  "conns_base": 180},
        "inventory-service":     {"tq": 0.2, "tc": 0.4,  "conns_base": 35},
        "payment-processor":     {"tq": 0.9, "tc": 0.8,  "conns_base": 28},  # high Tq = busy
        "auth-db":               {"tq": 0.1, "tc": 0.2,  "conns_base": 58},  # fast DB
        "data-pipeline":         {"tq": 2.8, "tc": 0.7,  "conns_base": 12},  # batch queue
    }

    # Seed service edge metrics (inter-service RED) for the last hour
    EDGES = [
        # Tier 0 → Tier 1: api-gateway is the front door to everything
        ("api-gateway",        "user-profile"),
        ("api-gateway",        "checkout-service"),
        ("api-gateway",        "auth-service"),
        ("api-gateway",        "search-service"),
        ("api-gateway",        "recommendation-engine"),
        # Tier 1 → Tier 2: downstream service calls
        ("checkout-service",   "payment-processor"),
        ("checkout-service",   "inventory-service"),
        ("user-profile",       "auth-service"),      # profile validates tokens
        # Tier 1/2 → Tier 3: data stores and pipelines
        ("auth-service",       "auth-db"),
        ("payment-processor",  "data-pipeline"),
        ("notification-service","data-pipeline"),
    ]

    edge_count = 0
    for minutes_ago in range(0, 61, 5):   # every 5 min for 1 hour
        ts = now - timedelta(minutes=minutes_ago)
        for src, dst in EDGES:
            src_p = PROFILES[src]
            dst_p = PROFILES[dst]
            hp    = HAPROXY.get(dst, {"tq": 0.3, "tc": 0.5, "conns_base": 30})

            p50 = dst_p["latency"][0] * rng.uniform(0.9, 1.1)
            p95 = dst_p["latency"][1] * rng.uniform(0.9, 1.2)
            p99 = dst_p["latency"][2] * rng.uniform(0.9, 1.3)
            if rng.random() < 0.08:   # occasional spike
                p99 *= rng.uniform(2, 4)

            # HAProxy timing: Tq and Tc are measured at the LB
            # Tr ≈ p50 (what the backend actually reported)
            # Tt = Tq + Tc + Tr (what the user actually experienced)
            tq = hp["tq"] * rng.uniform(0.8, 1.4)
            tc = hp["tc"] * rng.uniform(0.85, 1.2)
            tr = p50 * rng.uniform(0.95, 1.05)
            tt = tq + tc + tr

            active_conns = int(hp["conns_base"] * rng.uniform(0.85, 1.15))

            db.add(ServiceEdgeMetric(
                id=str(uuid4()),
                source_service=src,
                dest_service=dst,
                cluster="prod-us-east-1",
                timestamp=ts,
                p50_ms=round(p50, 1),
                p95_ms=round(p95, 1),
                p99_ms=round(p99, 1),
                rps=round(min(src_p["rps"], dst_p["rps"]) * rng.uniform(0.8, 1.0), 1),
                error_rate=round(max(src_p["error"], dst_p["error"]) * rng.uniform(0.8, 1.5), 5),
                org_id="default",
                queue_time_ms=round(tq, 3),
                connect_time_ms=round(tc, 3),
                backend_time_ms=round(tr, 1),
                total_time_ms=round(tt, 1),
                active_connections=active_conns,
            ))
            edge_count += 1

    print(f"     {count} signals across {len(PROFILES)} services")
    print(f"     {edge_count} edge metric readings across {len(EDGES)} service pairs (with HAProxy timing)")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Cortex synthetic data")
    parser.add_argument("--reset", action="store_true", help="Clear existing seeded data before inserting")
    args = parser.parse_args()

    print("Cortex data seeder")
    print("==================")
    print("Initialising database…")
    (ROOT / "data").mkdir(exist_ok=True)
    init_db()
    print("Database ready.\n")

    print("Seeding data…")
    db = SessionLocal()
    try:
        seed_all(db, reset=args.reset)
        print("\nAll done. Summary:")
        from app.db.models import Incident, Signal, LearnOutcome, NearMiss
        from sqlalchemy import select, func
        for Model, label in [
            (Incident, "incidents"),
            (Signal, "signals"),
            (LearnOutcome, "learn outcomes"),
            (NearMiss, "near misses"),
        ]:
            count = db.scalar(select(func.count(Model.id))) or 0
            print(f"  {count:>5}  {label}")
    finally:
        db.close()

    print("\nRun the app and open http://localhost:8080/dashboard")


if __name__ == "__main__":
    main()
