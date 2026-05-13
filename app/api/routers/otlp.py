"""OTLP/HTTP JSON ingest endpoints.

Apps set:
    OTEL_EXPORTER_OTLP_ENDPOINT=http://your-heron-host
    OTEL_EXPORTER_OTLP_PROTOCOL=http/json

Then traces flow to POST /otlp/v1/traces and metrics to POST /otlp/v1/metrics.
Both endpoints are spec-compliant OTLP/HTTP receivers.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse

from ...core import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/otlp/v1", tags=["otlp"])


@router.post("/traces")
async def ingest_traces(
    request: Request,
    x_heron_cluster: str | None = Header(default=None),
) -> dict[str, Any]:
    """Receive OTLP/HTTP JSON traces."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})

    cluster = x_heron_cluster or "default"
    from ...services.tracing.otel import ingest_traces as _ingest
    edges_written = _ingest(payload, cluster=cluster)
    return {"partialSuccess": {}, "edges_written": edges_written}


@router.post("/metrics")
async def ingest_metrics(request: Request) -> dict[str, Any]:
    """Receive OTLP/HTTP JSON metrics and push to Sense pipeline."""
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "invalid JSON"})

    from ...services.tracing.otel import ingest_metrics as _ingest
    signals = _ingest(payload)
    return {"partialSuccess": {}, "signals_written": signals}


@router.post("/logs")
async def ingest_logs(request: Request) -> dict[str, Any]:
    """Acknowledge OTLP log payloads (not yet processed)."""
    return {"partialSuccess": {}}
