"""PagerDuty integration — Events API v2.

Setup:
    1. Create a PagerDuty service with an "Events API v2" integration
    2. Copy the 32-char Integration Key (routing key)
    3. Set in .env:
           PAGERDUTY_ROUTING_KEY=your-32-char-key
           PAGERDUTY_DRY_RUN=false

Not wired into the escalation flow by default — Slack handles live
escalations for now. Add the routing key and flip DRY_RUN to activate.
"""

from __future__ import annotations

import json
import os
from typing import Dict

import requests

EVENTS_API_URL = "https://events.pagerduty.com/v2/enqueue"

_SEVERITY_MAP = {
    "sev1": "critical",
    "sev2": "error",
    "sev3": "warning",
    "sev4": "info",
    "info": "info",
}


def _routing_key() -> str:
    return os.getenv("PAGERDUTY_ROUTING_KEY", "").strip()


def _is_dry_run() -> bool:
    raw = os.getenv("PAGERDUTY_DRY_RUN", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def trigger_incident(
    *,
    target: str,
    message: str,
    severity: str = "sev1",
    service: str = "",
    region: str = "",
    environment: str = "prod",
    incident_id: str = "",
    chronicle_url: str = "",
    dry_run: bool | None = None,
) -> Dict[str, object]:
    """Trigger a PagerDuty incident via Events API v2.

    severity maps: sev1→critical, sev2→error, sev3→warning, sev4→info
    incident_id is used as dedup_key — prevents duplicate pages for the same incident.
    chronicle_url surfaces a direct link inside the PagerDuty alert.
    """
    effective_dry_run = _is_dry_run() if dry_run is None else dry_run
    pd_severity = _SEVERITY_MAP.get(severity.lower(), "error")
    dedup_key = incident_id or f"heron-{service}-{target}".replace(" ", "-").lower()

    if effective_dry_run:
        return {
            "ok": True, "channel": "pagerduty", "status": "dry_run",
            "dedup_key": dedup_key, "pd_severity": pd_severity, "message": message,
        }

    key = _routing_key()
    if not key:
        return {
            "ok": False, "channel": "pagerduty", "status": "error",
            "error": "PAGERDUTY_ROUTING_KEY not configured", "message": message,
        }

    payload: Dict = {
        "routing_key": key,
        "event_action": "trigger",
        "dedup_key": dedup_key,
        "payload": {
            "summary": message,
            "severity": pd_severity,
            "source": "heron",
            "component": service or target,
            "group": environment,
            "custom_details": {
                "service": service,
                "region": region,
                "environment": environment,
                "incident_id": incident_id,
                "heron_severity": severity,
            },
        },
    }
    if chronicle_url:
        payload["links"] = [{"href": chronicle_url, "text": "View in Chronicle →"}]

    try:
        resp = requests.post(
            EVENTS_API_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json() if resp.text else {}
        return {
            "ok": True, "channel": "pagerduty", "status": "triggered",
            "dedup_key": dedup_key, "pd_status": body.get("status"),
        }
    except Exception as exc:
        return {
            "ok": False, "channel": "pagerduty", "status": "error",
            "error": str(exc), "dedup_key": dedup_key, "message": message,
        }


def resolve_incident(*, incident_id: str, dry_run: bool | None = None) -> Dict[str, object]:
    """Resolve a PagerDuty incident by dedup key.

    Called when Heron auto-resolves so the page doesn't stay open.
    """
    effective_dry_run = _is_dry_run() if dry_run is None else dry_run
    if effective_dry_run:
        return {"ok": True, "channel": "pagerduty", "status": "dry_run",
                "dedup_key": incident_id}
    key = _routing_key()
    if not key:
        return {"ok": False, "channel": "pagerduty", "status": "error",
                "error": "PAGERDUTY_ROUTING_KEY not configured"}
    try:
        resp = requests.post(
            EVENTS_API_URL,
            data=json.dumps({"routing_key": key, "event_action": "resolve",
                             "dedup_key": incident_id}),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        return {"ok": True, "channel": "pagerduty", "status": "resolved",
                "dedup_key": incident_id}
    except Exception as exc:
        return {"ok": False, "channel": "pagerduty", "status": "error",
                "error": str(exc), "dedup_key": incident_id}
