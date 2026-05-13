"""Datadog alert puller — implements AlertSourceAdapter.

Pulls firing Monitors and Events from the Datadog API, converting them into
Heron SignalPayload format.  Works alongside (not against) existing Datadog
setups — Heron reads from Datadog rather than replacing it.

Setup (.env):
    DATADOG_API_KEY  = dd-api-...
    DATADOG_APP_KEY  = dd-app-...
    DATADOG_SITE     = datadoghq.com   (or datadoghq.eu, us3.datadoghq.com, etc.)

Activate in config/pullers.yaml:
    sources:
      datadog:
        enabled: true
        interval_seconds: 60
"""

from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

import requests

from ...core import get_logger
from ...schemas.signal import SignalPayload
from .alert_source import AlertSourceAdapter, AlertSourceResult

logger = get_logger(__name__)

_SEV_MAP = {
    "P1": "sev1",  # Critical
    "P2": "sev2",  # High
    "P3": "sev3",  # Medium
    "P4": "sev3",  # Low
}

_STATUS_SEV = {
    "Alert":        "sev2",
    "No Data":      "sev3",
    "Warn":         "sev3",
    "Triggered":    "sev2",
}


class DatadogPuller(AlertSourceAdapter):
    """Pulls firing monitors and events from the Datadog API."""

    @property
    def source_name(self) -> str:
        return "datadog"

    def is_configured(self) -> bool:
        return bool(
            os.getenv("DATADOG_API_KEY", "").strip()
            and os.getenv("DATADOG_APP_KEY", "").strip()
        )

    def _headers(self) -> Dict[str, str]:
        return {
            "DD-API-KEY":         os.getenv("DATADOG_API_KEY", ""),
            "DD-APPLICATION-KEY": os.getenv("DATADOG_APP_KEY", ""),
            "Content-Type":       "application/json",
        }

    def _base_url(self) -> str:
        site = os.getenv("DATADOG_SITE", "datadoghq.com").strip().rstrip("/")
        return f"https://api.{site}/api/v1"

    def _timeout(self) -> int:
        return 20

    def pull(
        self,
        *,
        range_hours: int,
        batch_size: int,
        cursor: Dict[str, Any] | None,
    ) -> AlertSourceResult:
        signals: List[SignalPayload] = []
        errors: List[Dict[str, Any]] = []

        # Firing monitors
        try:
            monitor_signals, monitor_errors = self._pull_monitors(batch_size)
            signals.extend(monitor_signals)
            errors.extend(monitor_errors)
        except Exception as exc:
            errors.append({"source": "datadog_monitors", "error": str(exc)})
            logger.warning("Datadog monitors pull failed: %s", exc)

        # Recent alert events
        try:
            event_signals, event_errors = self._pull_events(range_hours, batch_size)
            signals.extend(event_signals)
            errors.extend(event_errors)
        except Exception as exc:
            errors.append({"source": "datadog_events", "error": str(exc)})
            logger.debug("Datadog events pull failed: %s", exc)

        return AlertSourceResult(
            signals=signals[:batch_size],
            next_cursor={
                "last_run_utc": datetime.now(timezone.utc).isoformat(),
                "last_event_ts": int(datetime.now(timezone.utc).timestamp()),
            },
            errors=errors,
            metadata={"total_signals": len(signals)},
        )

    # ── Monitors ──────────────────────────────────────────────────────────

    def _pull_monitors(self, batch_size: int):
        url = f"{self._base_url()}/monitor"
        resp = requests.get(
            url,
            headers=self._headers(),
            params={
                "monitor_tags": "",       # all tags
                "with_downtimes": "false",
                "page_size": min(batch_size, 200),
                "page": 0,
            },
            timeout=self._timeout(),
        )
        resp.raise_for_status()
        monitors = resp.json() if resp.text else []

        signals = []
        for mon in monitors:
            overall_state = mon.get("overall_state", "")
            if overall_state not in ("Alert", "No Data", "Warn", "Triggered"):
                continue
            sig = self._monitor_to_signal(mon)
            if sig:
                signals.append(sig)

        logger.info("Datadog: %d firing monitors ingested", len(signals))
        return signals, []

    def _monitor_to_signal(self, mon: Dict[str, Any]) -> Optional[SignalPayload]:
        mid       = mon.get("id", uuid4().hex)
        name      = mon.get("name", "unknown monitor")
        state     = mon.get("overall_state", "Alert")
        severity  = _STATUS_SEV.get(state, "sev3")
        tags      = mon.get("tags", [])
        mon_type  = mon.get("type", "metric alert")

        # Extract service from tags (service:my-svc)
        service = next(
            (t.split(":", 1)[1] for t in tags if t.startswith("service:")),
            "unknown",
        )
        env = next(
            (t.split(":", 1)[1] for t in tags if t.startswith("env:")),
            "prod",
        )

        query = mon.get("query", "")
        metric_name = _extract_metric_name(query) or "datadog_monitor"

        return SignalPayload(
            signal_id=f"dd-mon-{mid}",
            type="event",
            detected_at=datetime.now(timezone.utc).replace(tzinfo=None),
            summary=f"[{state}] {name}",
            details={
                "metric_name": metric_name,
                "severity": severity,
                "threshold": 0,
                "observed": 1,
                "monitor_id": mid,
                "monitor_name": name,
                "monitor_type": mon_type,
                "state": state,
                "tags": tags,
                "source": "datadog",
            },
        )

    # ── Events ────────────────────────────────────────────────────────────

    def _pull_events(self, range_hours: int, batch_size: int):
        now_ts  = int(datetime.now(timezone.utc).timestamp())
        from_ts = now_ts - range_hours * 3600
        url = f"{self._base_url()}/events"
        resp = requests.get(
            url,
            headers=self._headers(),
            params={
                "start":    from_ts,
                "end":      now_ts,
                "priority": "normal",
                "count":    min(batch_size, 100),
                "tags":     "alert_type:error,alert_type:warning",
            },
            timeout=self._timeout(),
        )
        resp.raise_for_status()
        events = (resp.json() or {}).get("events", [])

        signals = []
        for ev in events:
            alert_type = ev.get("alert_type", "")
            if alert_type not in ("error", "warning"):
                continue
            signals.append(SignalPayload(
                signal_id=f"dd-ev-{ev.get('id', uuid4().hex)}",
                type="event",
                detected_at=datetime.fromtimestamp(
                    ev.get("date_happened", datetime.now(timezone.utc).timestamp()),
                    tz=timezone.utc,
                ).replace(tzinfo=None),
                summary=(ev.get("title") or "")[:300],
                details={
                    "metric_name": "datadog_event",
                    "severity": "sev2" if alert_type == "error" else "sev3",
                    "threshold": 0,
                    "observed": 1,
                    "alert_type": alert_type,
                    "tags": ev.get("tags", []),
                    "source": "datadog",
                },
            ))

        logger.info("Datadog: %d alert events ingested", len(signals))
        return signals, []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_metric_name(query: str) -> str:
    """Pull the metric name out of a Datadog monitor query string."""
    import re
    # e.g. "avg:system.cpu.user{*}" → system_cpu_user
    m = re.search(r"(?:avg:|sum:|max:|min:|count:)?([a-z][a-z0-9_.]+)\{", query)
    if m:
        return m.group(1).replace(".", "_")
    return ""


datadog_puller = DatadogPuller()
