"""OpsGenie integration — Alerts API v2.

NOTE: Direct OpsGenie signups were discontinued June 2025. OpsGenie is being
merged into Jira Service Management (JSM) Premium. This implementation is
kept for organisations that already have an OpsGenie account or access via
JSM Premium.

Setup:
    1. In OpsGenie / JSM: create an API integration, copy the API key
    2. Set in .env:
           OPSGENIE_API_KEY=your-api-key
           OPSGENIE_DRY_RUN=false

API region note: EU accounts use https://api.eu.opsgenie.com
Set OPSGENIE_API_URL to override the default (US) endpoint.
"""

from __future__ import annotations

import json
import os
from typing import Dict

import requests

DEFAULT_API_URL = "https://api.opsgenie.com/v2/alerts"

_PRIORITY_MAP = {
    "sev1": "P1",
    "sev2": "P2",
    "sev3": "P3",
    "sev4": "P4",
    "info": "P5",
}


def _api_key() -> str:
    return os.getenv("OPSGENIE_API_KEY", "").strip()


def _api_url() -> str:
    return os.getenv("OPSGENIE_API_URL", DEFAULT_API_URL).strip()


def _is_dry_run() -> bool:
    raw = os.getenv("OPSGENIE_DRY_RUN", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def create_alert(
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
    """Create an OpsGenie alert.

    severity maps: sev1→P1, sev2→P2, sev3→P3, sev4→P4
    incident_id is used as alias for deduplication.
    """
    effective_dry_run = _is_dry_run() if dry_run is None else dry_run
    priority = _PRIORITY_MAP.get(severity.lower(), "P2")
    alias = incident_id or f"heron-{service}-{target}".replace(" ", "-").lower()

    if effective_dry_run:
        return {
            "ok": True, "channel": "opsgenie", "status": "dry_run",
            "alias": alias, "priority": priority, "message": message,
        }

    key = _api_key()
    if not key:
        return {
            "ok": False, "channel": "opsgenie", "status": "error",
            "error": "OPSGENIE_API_KEY not configured", "message": message,
        }

    description_parts = [message]
    if chronicle_url:
        description_parts.append(f"Chronicle: {chronicle_url}")

    payload: Dict = {
        "message": message[:130],   # OpsGenie message limit: 130 chars
        "alias": alias,
        "description": "\n".join(description_parts),
        "priority": priority,
        "source": "heron",
        "entity": service or target,
        "tags": ["heron", severity, environment],
        "details": {
            "service": service,
            "region": region,
            "environment": environment,
            "incident_id": incident_id,
            "heron_severity": severity,
        },
    }

    try:
        resp = requests.post(
            _api_url(),
            data=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"GenieKey {key}",
            },
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json() if resp.text else {}
        return {
            "ok": True, "channel": "opsgenie", "status": "created",
            "alias": alias, "request_id": body.get("requestId"),
        }
    except Exception as exc:
        return {
            "ok": False, "channel": "opsgenie", "status": "error",
            "error": str(exc), "alias": alias, "message": message,
        }


def close_alert(*, incident_id: str, note: str = "Resolved by Heron",
                dry_run: bool | None = None) -> Dict[str, object]:
    """Close an OpsGenie alert by alias."""
    effective_dry_run = _is_dry_run() if dry_run is None else dry_run
    if effective_dry_run:
        return {"ok": True, "channel": "opsgenie", "status": "dry_run",
                "alias": incident_id}
    key = _api_key()
    if not key:
        return {"ok": False, "channel": "opsgenie", "status": "error",
                "error": "OPSGENIE_API_KEY not configured"}
    url = f"{_api_url()}/{incident_id}/close"
    try:
        resp = requests.post(
            url,
            data=json.dumps({"note": note}),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"GenieKey {key}",
            },
            params={"identifierType": "alias"},
            timeout=10,
        )
        resp.raise_for_status()
        return {"ok": True, "channel": "opsgenie", "status": "closed",
                "alias": incident_id}
    except Exception as exc:
        return {"ok": False, "channel": "opsgenie", "status": "error",
                "error": str(exc), "alias": incident_id}
