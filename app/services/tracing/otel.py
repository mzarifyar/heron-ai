"""OTel Collector OTLP/HTTP ingest — accepts traces and metrics in JSON format.

Receives OTLP/HTTP JSON payloads and:
- Traces  → extracts service-to-service edges + latency → ServiceEdgeMetric
- Metrics → normalises to Heron Signal format → sense pipeline

No protobuf library required — OTLP/HTTP JSON is fully spec-compliant.
Apps point OTEL_EXPORTER_OTLP_ENDPOINT at this server.  Set the protocol
to http/json (the default for most SDK v0.x builds).

Env vars:
    OTLP_ENABLED = true    (default: true — the route is always registered)
    OTLP_MAX_SPANS_PER_BATCH = 5000
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ...core import get_logger
from .base import EdgeSample, write_edges

logger = get_logger(__name__)

_MAX_SPANS = int(os.getenv("OTLP_MAX_SPANS_PER_BATCH", "5000"))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _attr_str(attrs: list[dict], key: str) -> str:
    for a in attrs or []:
        if a.get("key") == key:
            return str((a.get("value") or {}).get("stringValue", ""))
    return ""


def _attr_int(attrs: list[dict], key: str) -> int:
    for a in attrs or []:
        if a.get("key") == key:
            v = a.get("value") or {}
            return int(v.get("intValue", 0) or v.get("doubleValue", 0) or 0)
    return 0


# ── Traces → EdgeSamples ──────────────────────────────────────────────────────

def ingest_traces(payload: dict[str, Any], cluster: str = "default") -> int:
    """Parse OTLP/HTTP JSON trace payload and write service edges."""
    resource_spans = payload.get("resourceSpans", [])
    if not resource_spans:
        return 0

    # Build span index for parent-lookup
    all_spans: list[tuple[str, dict, str]] = []  # (service, span, parent_span_id)
    for rs in resource_spans:
        resource_attrs = (rs.get("resource") or {}).get("attributes", [])
        service = _attr_str(resource_attrs, "service.name") or "unknown"
        for ss in rs.get("scopeSpans", []):
            for span in ss.get("spans", []):
                parent_id = span.get("parentSpanId", "")
                all_spans.append((service, span, parent_id))

    span_svc: dict[str, str] = {s.get("spanId", ""): svc for svc, s, _ in all_spans}

    edges: dict[tuple[str, str], list[float]] = {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    for service, span, parent_span_id in all_spans[:_MAX_SPANS]:
        start_ns = int(span.get("startTimeUnixNano", 0) or 0)
        end_ns   = int(span.get("endTimeUnixNano", 0) or 0)
        dur_ms   = max(0.0, (end_ns - start_ns) / 1e6)

        if parent_span_id and parent_span_id in span_svc:
            parent_svc = span_svc[parent_span_id]
            if parent_svc != service:
                edges.setdefault((parent_svc, service), []).append(dur_ms)

    result = []
    for (src, dst), durations in edges.items():
        durations.sort()
        n = len(durations)
        result.append(EdgeSample(
            source=src, dest=dst,
            p50_ms=round(durations[n // 2], 2),
            p95_ms=round(durations[min(int(n * 0.95), n - 1)], 2),
            p99_ms=round(durations[min(int(n * 0.99), n - 1)], 2),
            rps=round(n / 60.0, 2),   # rough RPS assuming 1-minute flush window
            cluster=cluster, timestamp=now,
        ))

    written = write_edges(result)
    logger.info("OTLP traces ingest: %d spans → %d edges", len(all_spans), written)
    return written


# ── Metrics → Signal pipeline ─────────────────────────────────────────────────

def ingest_metrics(payload: dict[str, Any]) -> int:
    """Parse OTLP/HTTP JSON metrics payload and push to the Sense pipeline."""
    resource_metrics = payload.get("resourceMetrics", [])
    if not resource_metrics:
        return 0

    from ...schemas.signal import SignalContext, SignalIngestRequest, SignalMetric, SignalPayload
    from ...services.sense import sense_service

    signals: list[SignalPayload] = []

    for rm in resource_metrics:
        resource_attrs = (rm.get("resource") or {}).get("attributes", [])
        service = _attr_str(resource_attrs, "service.name") or "unknown"
        region  = _attr_str(resource_attrs, "cloud.region") or "unknown"
        env     = _attr_str(resource_attrs, "deployment.environment") or "prod"

        for sm in rm.get("scopeMetrics", []):
            for metric in sm.get("metrics", []):
                name = metric.get("name", "")
                # Only handle gauge and sum (ignore histograms for now)
                data_points: list[dict] = (
                    metric.get("gauge", {}).get("dataPoints", [])
                    or metric.get("sum", {}).get("dataPoints", [])
                )
                for dp in data_points:
                    value = float(dp.get("asDouble", dp.get("asInt", 0)) or 0)
                    ts_ns = int(dp.get("timeUnixNano", 0) or 0)
                    detected_at = (
                        datetime.fromtimestamp(ts_ns / 1e9, tz=timezone.utc).replace(tzinfo=None)
                        if ts_ns else datetime.utcnow()
                    )
                    signals.append(SignalPayload(
                        signal_id=f"otlp-{uuid4().hex[:10]}",
                        type="metric",
                        detected_at=detected_at,
                        summary=f"{name}={value:.4f} on {service}",
                        metric=SignalMetric(name=name, value=value),
                        details={
                            "metric_name": name,
                            "severity": "info",
                            "threshold": 0,
                            "observed": value,
                            "source": "otlp",
                        },
                    ))

    if not signals:
        return 0

    try:
        ctx = SignalContext(service="otlp-ingest", tier="backend", environment="prod", region="unknown")
        req = SignalIngestRequest(source="otlp", context=ctx, signals=signals[:500])
        sense_service.process(req)
        logger.info("OTLP metrics ingest: %d signals pushed to Sense", len(signals))
        return len(signals)
    except Exception as exc:
        logger.warning("OTLP metrics ingest failed: %s", exc)
        return 0
