"""Distributed tracing connector — Jaeger, Zipkin, and Tempo.

Queries the REST API of an existing tracing system during active incidents
to extract service-to-service latency from span data, then writes to
ServiceEdgeMetric so the service map shows real observed latency.

Also runs on a polling schedule to keep the baseline topology fresh.

Setup (env vars — any one is enough):
    JAEGER_URL  = http://jaeger:16686
    ZIPKIN_URL  = http://zipkin:9411
    TEMPO_URL   = http://tempo:3200
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

from ...core import get_logger
from .base import EdgeSample, write_edges, _env

logger = get_logger(__name__)

_TIMEOUT = 15


# ── Jaeger ────────────────────────────────────────────────────────────────────

def _jaeger_services(base: str) -> list[str]:
    try:
        r = requests.get(f"{base}/api/services", timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception:
        return []


def _jaeger_traces(base: str, service: str, lookback_minutes: int = 5) -> list[dict]:
    end = int(datetime.now(timezone.utc).timestamp() * 1_000_000)
    start = end - lookback_minutes * 60 * 1_000_000
    try:
        r = requests.get(
            f"{base}/api/traces",
            params={"service": service, "start": start, "end": end, "limit": 100},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        return r.json().get("data", [])
    except Exception as exc:
        logger.debug("Jaeger traces fetch failed for %s: %s", service, exc)
        return []


def _edges_from_jaeger_traces(traces: list[dict], cluster: str) -> list[EdgeSample]:
    """Extract parent→child service edges from Jaeger trace spans."""
    edges: dict[tuple[str, str], list[float]] = {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for trace in traces:
        spans = trace.get("spans", [])
        processes = trace.get("processes", {})

        span_by_id: dict[str, dict] = {s["spanID"]: s for s in spans}

        for span in spans:
            duration_us = span.get("duration", 0)
            duration_ms = duration_us / 1000.0
            process_key = span.get("processID", "")
            service = (processes.get(process_key) or {}).get("serviceName", "")
            if not service:
                continue
            refs = span.get("references", [])
            for ref in refs:
                if ref.get("refType") == "CHILD_OF":
                    parent_span = span_by_id.get(ref.get("spanID", ""))
                    if parent_span:
                        parent_process = parent_span.get("processID", "")
                        parent_service = (processes.get(parent_process) or {}).get("serviceName", "")
                        if parent_service and parent_service != service:
                            key = (parent_service, service)
                            edges.setdefault(key, []).append(duration_ms)

    result = []
    for (src, dst), durations in edges.items():
        durations.sort()
        n = len(durations)
        p50 = durations[n // 2]
        p95 = durations[int(n * 0.95)]
        p99 = durations[int(n * 0.99)]
        result.append(EdgeSample(
            source=src, dest=dst,
            p50_ms=round(p50, 2), p95_ms=round(p95, 2), p99_ms=round(p99, 2),
            rps=round(n / 300.0, 2),  # rough: n spans over 5-minute window
            cluster=cluster, timestamp=now,
        ))
    return result


def poll_jaeger(cluster: str = "default") -> int:
    base = _env("JAEGER_URL").rstrip("/")
    if not base:
        return 0
    services = _jaeger_services(base)
    if not services:
        logger.debug("Jaeger: no services found at %s", base)
        return 0
    all_edges: list[EdgeSample] = []
    for svc in services[:20]:  # cap to avoid overloading
        traces = _jaeger_traces(base, svc)
        all_edges.extend(_edges_from_jaeger_traces(traces, cluster))
    written = write_edges(all_edges)
    logger.info("Jaeger connector: %d edges from %d services", written, len(services))
    return written


# ── Zipkin ────────────────────────────────────────────────────────────────────

def poll_zipkin(cluster: str = "default") -> int:
    base = _env("ZIPKIN_URL").rstrip("/")
    if not base:
        return 0
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = end_ms - 5 * 60 * 1000
    try:
        r = requests.get(
            f"{base}/api/v2/traces",
            params={"endTs": end_ms, "lookback": 300000, "limit": 200},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        traces = r.json()
    except Exception as exc:
        logger.debug("Zipkin fetch failed: %s", exc)
        return 0

    edges: dict[tuple[str, str], list[float]] = {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for trace in traces:
        span_by_id: dict[str, dict] = {}
        for span in trace:
            span_by_id[span.get("id", "")] = span

        for span in trace:
            service = (span.get("localEndpoint") or {}).get("serviceName", "")
            parent_id = span.get("parentId")
            duration_us = span.get("duration", 0)
            if not service or not parent_id:
                continue
            parent = span_by_id.get(parent_id, {})
            parent_service = (parent.get("localEndpoint") or {}).get("serviceName", "")
            if parent_service and parent_service != service:
                key = (parent_service, service)
                edges.setdefault(key, []).append(duration_us / 1000.0)

    result = []
    for (src, dst), durations in edges.items():
        durations.sort()
        n = len(durations)
        result.append(EdgeSample(
            source=src, dest=dst,
            p50_ms=round(durations[n // 2], 2),
            p95_ms=round(durations[min(int(n * 0.95), n - 1)], 2),
            p99_ms=round(durations[min(int(n * 0.99), n - 1)], 2),
            rps=round(n / 300.0, 2),
            cluster=cluster, timestamp=now,
        ))
    written = write_edges(result)
    logger.info("Zipkin connector: %d edges from %d traces", written, len(traces))
    return written


# ── Tempo ─────────────────────────────────────────────────────────────────────

def poll_tempo(cluster: str = "default") -> int:
    """Tempo exposes a Jaeger-compatible query API at /api/traces."""
    base = _env("TEMPO_URL").rstrip("/")
    if not base:
        return 0
    try:
        # Tempo's search endpoint
        r = requests.get(
            f"{base}/api/search",
            params={"limit": 100, "start": int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()), "end": int(datetime.now(timezone.utc).timestamp())},
            timeout=_TIMEOUT,
        )
        r.raise_for_status()
        trace_ids = [t["traceID"] for t in r.json().get("traces", [])]
    except Exception as exc:
        logger.debug("Tempo search failed: %s", exc)
        return 0

    edges: dict[tuple[str, str], list[float]] = {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for trace_id in trace_ids[:50]:
        try:
            r = requests.get(f"{base}/api/traces/{trace_id}", timeout=_TIMEOUT)
            r.raise_for_status()
            batches = r.json().get("batches", [])
            # Tempo returns OTLP-format protobuf decoded to JSON
            for batch in batches:
                resource = batch.get("resource", {})
                svc = next((a["value"].get("stringValue", "") for a in resource.get("attributes", []) if a.get("key") == "service.name"), "")
                for scope_span in batch.get("scopeSpans", []):
                    for span in scope_span.get("spans", []):
                        dur_ns = int(span.get("endTimeUnixNano", 0)) - int(span.get("startTimeUnixNano", 0))
                        parent_id = span.get("parentSpanId")
                        if parent_id and svc:
                            edges.setdefault(("upstream", svc), []).append(dur_ns / 1e6)
        except Exception:
            continue

    result = []
    for (src, dst), durations in edges.items():
        durations.sort()
        n = len(durations)
        result.append(EdgeSample(
            source=src, dest=dst,
            p50_ms=round(durations[n // 2], 2),
            p99_ms=round(durations[min(int(n * 0.99), n - 1)], 2),
            rps=round(n / 300.0, 2),
            cluster=cluster, timestamp=now,
        ))
    written = write_edges(result)
    logger.info("Tempo connector: %d edges from %d traces", written, len(trace_ids))
    return written


# ── Dispatcher ────────────────────────────────────────────────────────────────

def poll(cluster: str = "default") -> int:
    """Poll whichever tracing system is configured. Returns total edges written."""
    total = 0
    total += poll_jaeger(cluster)
    total += poll_zipkin(cluster)
    total += poll_tempo(cluster)
    return total
