"""Tracing connector scheduler — polls all configured sources on a timer.

Runs as a background thread (same pattern as the puller scheduler).
Controlled by config/pullers.yaml under the `tracing` key.

Each poll cycle:
  1. eBPF / Pixie   — if PIXIE_API_KEY set (or demo mode)
  2. Service mesh   — if MESH_PROMETHEUS_URL set
  3. Jaeger         — if JAEGER_URL set
  4. Zipkin         — if ZIPKIN_URL set
  5. Tempo          — if TEMPO_URL set

Results from all sources are written to ServiceEdgeMetric and immediately
visible on the service map and tracing graph endpoint.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from ...core import get_logger

logger = get_logger(__name__)

_DEFAULT_INTERVAL = 30   # seconds


class TracingScheduler:
    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._interval = _DEFAULT_INTERVAL

    def start(self, interval_seconds: int = _DEFAULT_INTERVAL) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._interval = interval_seconds
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, name="tracing-scheduler", daemon=True)
        self._thread.start()
        logger.info("Tracing scheduler started (interval=%ds)", interval_seconds)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._poll_all()
            except Exception as exc:
                logger.warning("Tracing scheduler poll error: %s", exc)
            self._stop_event.wait(self._interval)

    def _poll_all(self) -> dict[str, int]:
        results: dict[str, int] = {}
        cluster = os.getenv("HERON_KUBE_CLUSTER", "default")

        # eBPF / Pixie
        try:
            from .ebpf import poll as ebpf_poll
            demo = not os.getenv("PIXIE_API_KEY", "").strip()
            results["ebpf"] = ebpf_poll(cluster=cluster, demo=demo)
        except Exception as exc:
            logger.debug("eBPF poll error: %s", exc)

        # Service mesh (Istio / Linkerd / Cilium)
        if os.getenv("MESH_PROMETHEUS_URL") or os.getenv("PROMETHEUS_URL"):
            try:
                from .mesh import poll as mesh_poll
                results["mesh"] = mesh_poll(cluster=cluster)
            except Exception as exc:
                logger.debug("Mesh poll error: %s", exc)

        # Distributed tracing (Jaeger / Zipkin / Tempo)
        if any(os.getenv(k) for k in ("JAEGER_URL", "ZIPKIN_URL", "TEMPO_URL")):
            try:
                from .tracer import poll as tracer_poll
                results["tracer"] = tracer_poll(cluster=cluster)
            except Exception as exc:
                logger.debug("Tracer poll error: %s", exc)

        total = sum(results.values())
        if total:
            logger.info("Tracing poll: %d edges written %s", total, results)
        return results

    def poll_now(self) -> dict[str, int]:
        """Trigger an immediate poll outside the schedule (e.g. on-demand from API)."""
        return self._poll_all()


tracing_scheduler = TracingScheduler()
