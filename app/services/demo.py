"""Demo mode — generates synthetic incidents so Cortex can be evaluated without real infrastructure.

Enable with CORTEX_DEMO_MODE=true (or --demo flag). A background thread injects a rotating
set of realistic-looking signals every 30 seconds, driving the full closed loop:
Sense → Insight → Core → Reflex → Verify → Escalate → Chronicle.
"""

from __future__ import annotations

import random
import threading
import time
from datetime import datetime, timezone
from typing import List

from ..core import get_logger, get_settings
from ..schemas.signal import SignalContext, SignalIngestRequest, SignalMetric, SignalPayload
from .sense import sense_service

logger = get_logger(__name__)

_DEMO_SERVICES = [
    ("checkout-api", "backend", "prod"),
    ("auth-service", "mid", "prod"),
    ("inventory-worker", "batch", "prod"),
    ("payments-gateway", "backend", "prod"),
    ("notification-service", "mid", "stage"),
]

_DEMO_SCENARIOS = [
    {
        "summary": "CPU saturation on {service} — p99 latency spike detected",
        "metric_value": lambda: random.uniform(0.85, 0.99),
        "unit": "ratio",
        "details": lambda svc: {"threshold": 0.80, "window": "5m", "source": "demo"},
    },
    {
        "summary": "Error rate elevated on {service} — 5xx responses above threshold",
        "metric_value": lambda: random.uniform(0.05, 0.25),
        "unit": "ratio",
        "details": lambda svc: {"threshold": 0.02, "error_codes": ["500", "503"], "source": "demo"},
    },
    {
        "summary": "Pod CrashLoopBackOff detected in {service}",
        "metric_value": lambda: float(random.randint(1, 5)),
        "unit": "count",
        "details": lambda svc: {"namespace": "default", "pod_count": random.randint(1, 3), "source": "demo"},
    },
    {
        "summary": "Memory pressure on {service} — OOM risk in {window}",
        "metric_value": lambda: random.uniform(0.88, 0.97),
        "unit": "ratio",
        "details": lambda svc: {"threshold": 0.85, "window": "10m", "source": "demo"},
    },
    {
        "summary": "Disk I/O wait elevated on {service} storage tier",
        "metric_value": lambda: random.uniform(0.60, 0.90),
        "unit": "ratio",
        "details": lambda svc: {"threshold": 0.50, "device": "/dev/sda1", "source": "demo"},
    },
]


def _make_signal(service: str, tier: str, env: str, region: str) -> SignalIngestRequest:
    scenario = random.choice(_DEMO_SCENARIOS)
    now = datetime.now(timezone.utc)
    signal_id = f"demo-{service}-{int(now.timestamp())}-{random.randint(1000, 9999)}"
    window = random.choice(["2m", "5m", "10m"])
    summary = scenario["summary"].format(service=service, window=window)
    return SignalIngestRequest(
        source="demo",
        context=SignalContext(
            service=service,
            tier=tier,  # type: ignore[arg-type]
            environment=env,  # type: ignore[arg-type]
            region=region,
            component=f"{service}-{random.choice(['primary', 'replica', 'worker'])}",
            labels={"demo": "true", "synthetic": "true"},
        ),
        signals=[
            SignalPayload(
                signal_id=signal_id,
                type="metric",
                detected_at=now,
                metric=SignalMetric(
                    value=scenario["metric_value"](),
                    unit=scenario["unit"],
                    window_seconds=int(window[:-1]) * 60,
                ),
                summary=summary,
                details=scenario["details"](service),
            )
        ],
    )


class DemoRunner:
    """Injects synthetic signals on a background thread when CORTEX_DEMO_MODE=true."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        settings = get_settings()
        if not settings.demo_mode:
            return
        logger.info("CORTEX_DEMO_MODE=true — starting synthetic incident generator")
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="demo-runner", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _loop(self) -> None:
        settings = get_settings()
        region = settings.region
        interval = 30

        while not self._stop.wait(timeout=interval):
            try:
                service, tier, env = random.choice(_DEMO_SERVICES)
                request = _make_signal(service, tier, env, region)
                result = sense_service.ingest(request, token=None)
                logger.info(
                    "Demo signal injected",
                    extra={
                        "service": service,
                        "accepted": result.accepted,
                        "dropped": result.dropped,
                    },
                )
            except Exception as exc:
                logger.warning("Demo signal injection failed: %s", exc)


demo_runner = DemoRunner()
