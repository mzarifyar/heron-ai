"""Shared helpers for all tracing/mesh/eBPF adapters.

All adapters produce EdgeSample objects and call write_edges() to persist
them to the ServiceEdgeMetric table.  The service map and tracing graph
endpoint read from that table, so any adapter that writes here feeds
the live topology view automatically.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from ...core import get_logger

logger = get_logger(__name__)


@dataclass
class EdgeSample:
    """Metrics for a single source→dest service edge at a point in time."""
    source: str
    dest: str
    p50_ms: float = 0.0
    p95_ms: float = 0.0
    p99_ms: float = 0.0
    rps: float = 0.0
    error_rate: float = 0.0
    active_connections: int = 0
    cluster: str = "default"
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def is_valid(self) -> bool:
        return bool(self.source and self.dest and self.source != self.dest)


def write_edges(edges: list[EdgeSample]) -> int:
    """Persist a batch of EdgeSamples to ServiceEdgeMetric. Returns rows written."""
    if not edges:
        return 0
    try:
        from ...db.base import SessionLocal
        from ...db.models import ServiceEdgeMetric
        with SessionLocal() as db:
            for e in edges:
                if not e.is_valid():
                    continue
                db.add(ServiceEdgeMetric(
                    id=str(uuid4()),
                    source_service=e.source,
                    dest_service=e.dest,
                    cluster=e.cluster,
                    timestamp=e.timestamp,
                    p50_ms=round(e.p50_ms, 3),
                    p95_ms=round(e.p95_ms, 3),
                    p99_ms=round(e.p99_ms, 3),
                    rps=round(e.rps, 3),
                    error_rate=round(e.error_rate, 6),
                    active_connections=e.active_connections,
                ))
            db.commit()
        return len(edges)
    except Exception as exc:
        logger.warning("write_edges failed: %s", exc)
        return 0


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _parse_prom_histogram_quantile(
    metrics_text: str,
    metric_prefix: str,
    quantile: str,
    source_label: str = "source_workload",
    dest_label: str = "destination_workload",
) -> dict[tuple[str, str], float]:
    """Parse a Prometheus /metrics response for a histogram_quantile metric."""
    results: dict[tuple[str, str], float] = {}
    for line in metrics_text.splitlines():
        line = line.strip()
        if line.startswith("#") or not line:
            continue
        if metric_prefix not in line:
            continue
        try:
            # e.g.  istio_request_duration_milliseconds{...quantile="0.99",...} 145.2
            if f'quantile="{quantile}"' not in line:
                continue
            labels_raw = line[line.index("{") + 1: line.index("}")]
            value_str = line[line.index("}") + 1:].strip().split()[0]
            value = float(value_str)
            labels: dict[str, str] = {}
            for part in labels_raw.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    labels[k.strip()] = v.strip().strip('"')
            src = labels.get(source_label, "")
            dst = labels.get(dest_label, "")
            if src and dst and src != "unknown" and dst != "unknown":
                results[(src, dst)] = value
        except Exception:
            continue
    return results


def _parse_prom_counter(
    metrics_text: str,
    metric_name: str,
    source_label: str = "source_workload",
    dest_label: str = "destination_workload",
) -> dict[tuple[str, str], float]:
    """Parse a simple counter metric grouped by source/dest labels."""
    results: dict[tuple[str, str], float] = {}
    for line in metrics_text.splitlines():
        line = line.strip()
        if line.startswith("#") or not line or metric_name not in line:
            continue
        try:
            labels_raw = line[line.index("{") + 1: line.index("}")]
            value_str = line[line.index("}") + 1:].strip().split()[0]
            value = float(value_str)
            labels: dict[str, str] = {}
            for part in labels_raw.split(","):
                if "=" in part:
                    k, v = part.split("=", 1)
                    labels[k.strip()] = v.strip().strip('"')
            src = labels.get(source_label, "")
            dst = labels.get(dest_label, "")
            if src and dst and src != "unknown" and dst != "unknown":
                key = (src, dst)
                results[key] = results.get(key, 0.0) + value
        except Exception:
            continue
    return results
