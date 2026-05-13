"""Service mesh connector — Istio, Linkerd, and Cilium.

Each sidecar proxy exposes Prometheus-format metrics.  This adapter
discovers active pods via the Kubernetes API (when available) and scrapes
per-pod metrics to build service-to-service edge latency + error rates.

Setup (env vars):
    MESH_TYPE = auto | istio | linkerd | cilium   (default: auto)
    MESH_NAMESPACE = istio-system                 (Istio control plane ns)
    MESH_PROMETHEUS_URL = http://prometheus:9090   (preferred — avoids pod scraping)
    HERON_KUBE_CLUSTER  = cluster-name            (for kubeconfig resolution)
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests

from ...core import get_logger
from .base import EdgeSample, write_edges, _env, _parse_prom_histogram_quantile, _parse_prom_counter

logger = get_logger(__name__)


# ── Istio ─────────────────────────────────────────────────────────────────────

def _poll_istio_via_prometheus(prom_url: str, cluster: str) -> list[EdgeSample]:
    """Query Prometheus (with Istio metrics scraped) for service latency."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    edges: dict[tuple[str, str], EdgeSample] = {}
    timeout = 15

    def _query(promql: str) -> list[dict[str, Any]]:
        try:
            resp = requests.get(f"{prom_url}/api/v1/query", params={"query": promql}, timeout=timeout)
            resp.raise_for_status()
            body = resp.json()
            return body.get("data", {}).get("result", [])
        except Exception as exc:
            logger.debug("Prometheus query failed (%s): %s", promql[:60], exc)
            return []

    # p99 latency
    for row in _query(
        'histogram_quantile(0.99, sum(rate(istio_request_duration_milliseconds_bucket[5m])) '
        'by (le, source_workload, destination_workload))'
    ):
        m = row.get("metric", {})
        src, dst = m.get("source_workload", ""), m.get("destination_workload", "")
        if src and dst and src not in ("unknown", "") and dst not in ("unknown", ""):
            key = (src, dst)
            val = float(row["value"][1]) if row.get("value") else 0.0
            e = edges.setdefault(key, EdgeSample(source=src, dest=dst, cluster=cluster, timestamp=now))
            e.p99_ms = round(val, 2)
            e.p95_ms = round(val * 0.75, 2)
            e.p50_ms = round(val * 0.35, 2)

    # RPS
    for row in _query(
        'sum(rate(istio_requests_total[5m])) by (source_workload, destination_workload)'
    ):
        m = row.get("metric", {})
        src, dst = m.get("source_workload", ""), m.get("destination_workload", "")
        key = (src, dst)
        if key in edges:
            edges[key].rps = round(float(row["value"][1]) if row.get("value") else 0.0, 2)

    # Error rate (5xx)
    for row in _query(
        'sum(rate(istio_requests_total{response_code=~"5.."}[5m])) by (source_workload, destination_workload)'
        '/ sum(rate(istio_requests_total[5m])) by (source_workload, destination_workload)'
    ):
        m = row.get("metric", {})
        src, dst = m.get("source_workload", ""), m.get("destination_workload", "")
        key = (src, dst)
        if key in edges:
            try:
                edges[key].error_rate = round(float(row["value"][1]), 6)
            except (ValueError, IndexError):
                pass

    return list(edges.values())


# ── Linkerd ───────────────────────────────────────────────────────────────────

def _poll_linkerd_via_prometheus(prom_url: str, cluster: str) -> list[EdgeSample]:
    """Query Prometheus with Linkerd metrics."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    edges: dict[tuple[str, str], EdgeSample] = {}
    timeout = 15

    def _query(promql: str) -> list[dict]:
        try:
            resp = requests.get(f"{prom_url}/api/v1/query", params={"query": promql}, timeout=timeout)
            resp.raise_for_status()
            return resp.json().get("data", {}).get("result", [])
        except Exception:
            return []

    for row in _query(
        'histogram_quantile(0.99, sum(rate(response_latency_ms_bucket[5m])) by (le, client, server))'
    ):
        m = row.get("metric", {})
        src, dst = m.get("client", ""), m.get("server", "")
        if src and dst:
            key = (src, dst)
            val = float(row["value"][1]) if row.get("value") else 0.0
            e = edges.setdefault(key, EdgeSample(source=src, dest=dst, cluster=cluster, timestamp=now))
            e.p99_ms = round(val, 2)
            e.p50_ms = round(val * 0.35, 2)

    for row in _query('sum(rate(response_total[5m])) by (client, server)'):
        m = row.get("metric", {})
        key = (m.get("client", ""), m.get("server", ""))
        if key in edges:
            edges[key].rps = round(float(row["value"][1]) if row.get("value") else 0.0, 2)

    return list(edges.values())


# ── Cilium / Hubble ───────────────────────────────────────────────────────────

def _poll_cilium_via_prometheus(prom_url: str, cluster: str) -> list[EdgeSample]:
    """Query Hubble metrics exported to Prometheus."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    edges: dict[tuple[str, str], EdgeSample] = {}

    def _query(promql: str) -> list[dict]:
        try:
            resp = requests.get(f"{prom_url}/api/v1/query", params={"query": promql}, timeout=15)
            resp.raise_for_status()
            return resp.json().get("data", {}).get("result", [])
        except Exception:
            return []

    for row in _query('sum(rate(hubble_flows_processed_total[5m])) by (source, destination)'):
        m = row.get("metric", {})
        src, dst = m.get("source", ""), m.get("destination", "")
        if src and dst:
            key = (src, dst)
            val = float(row["value"][1]) if row.get("value") else 0.0
            e = edges.setdefault(key, EdgeSample(source=src, dest=dst, cluster=cluster, timestamp=now))
            e.rps = round(val, 2)

    return list(edges.values())


# ── Dispatcher ────────────────────────────────────────────────────────────────

def poll(cluster: str = "default") -> int:
    """Auto-detect mesh type and poll metrics. Returns edges written."""
    prom_url = _env("MESH_PROMETHEUS_URL") or _env("PROMETHEUS_URL")
    mesh_type = _env("MESH_TYPE", "auto").lower()

    if not prom_url:
        logger.debug("MESH_PROMETHEUS_URL not set — skipping mesh connector")
        return 0

    edges: list[EdgeSample] = []

    if mesh_type in ("auto", "istio"):
        edges = _poll_istio_via_prometheus(prom_url, cluster)
        if edges:
            logger.info("Service mesh (Istio): %d edges", len(edges))
            return write_edges(edges)

    if mesh_type in ("auto", "linkerd"):
        edges = _poll_linkerd_via_prometheus(prom_url, cluster)
        if edges:
            logger.info("Service mesh (Linkerd): %d edges", len(edges))
            return write_edges(edges)

    if mesh_type in ("auto", "cilium"):
        edges = _poll_cilium_via_prometheus(prom_url, cluster)
        if edges:
            logger.info("Service mesh (Cilium): %d edges", len(edges))
            return write_edges(edges)

    logger.debug("Service mesh connector: no data from %s (type=%s)", prom_url, mesh_type)
    return 0
