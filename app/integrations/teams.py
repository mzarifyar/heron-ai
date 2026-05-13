"""Microsoft Teams integration — Incoming Webhook with Adaptive Cards.

Setup:
    1. In Teams: channel → ··· → Connectors → Incoming Webhook → Create
    2. Copy the webhook URL
    3. Set in .env:
           TEAMS_WEBHOOK_URL=https://outlook.office.com/webhook/...
           TEAMS_DRY_RUN=false

Adaptive Cards give rich formatting with incident severity colours,
action buttons, and structured metadata — much richer than plain text.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Dict, Any

import requests

_SEVERITY_COLOUR = {
    "sev1": "attention",    # red
    "sev2": "warning",      # orange
    "sev3": "warning",      # orange
    "sev4": "good",         # green
    "info": "default",
}

_SEVERITY_EMOJI = {
    "sev1": "🔴",
    "sev2": "🟠",
    "sev3": "🟡",
    "sev4": "🟢",
    "info": "ℹ️",
}


def _webhook_url() -> str:
    return os.getenv("TEAMS_WEBHOOK_URL", "").strip()


def _is_dry_run() -> bool:
    raw = os.getenv("TEAMS_DRY_RUN", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def _adaptive_card(
    title: str,
    message: str,
    severity: str = "sev3",
    service: str = "",
    incident_id: str = "",
    chronicle_url: str = "",
) -> dict[str, Any]:
    """Build an Adaptive Card payload for Teams."""
    colour    = _SEVERITY_COLOUR.get(severity, "default")
    emoji     = _SEVERITY_EMOJI.get(severity, "ℹ️")
    ts        = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    facts = [{"title": "Severity", "value": f"{emoji} {severity.upper()}"}]
    if service:
        facts.append({"title": "Service", "value": service})
    if incident_id:
        facts.append({"title": "Incident", "value": incident_id})
    facts.append({"title": "Time", "value": ts})
    facts.append({"title": "Source", "value": "Heron"})

    body: list[dict] = [
        {
            "type": "TextBlock",
            "text": title,
            "weight": "Bolder",
            "size": "Medium",
            "color": colour,
            "wrap": True,
        },
        {
            "type": "FactSet",
            "facts": facts,
        },
        {
            "type": "TextBlock",
            "text": message,
            "wrap": True,
            "color": "Default",
        },
    ]

    actions = []
    if chronicle_url:
        actions.append({
            "type": "Action.OpenUrl",
            "title": "View in Chronicle →",
            "url": chronicle_url,
        })

    card: dict[str, Any] = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": body,
                **({"actions": actions} if actions else {}),
            },
        }],
    }
    return card


def send_message(
    *,
    target: str,
    message: str,
    severity: str = "sev3",
    service: str = "",
    incident_id: str = "",
    chronicle_url: str = "",
    dry_run: bool | None = None,
) -> Dict[str, object]:
    """Send an Adaptive Card to Teams via Incoming Webhook.

    Args:
        target:       Channel label (informational — the webhook is pre-bound to a channel).
        message:      Body text of the notification.
        severity:     Heron severity (sev1–sev4) — sets card accent colour.
        dry_run:      None = read TEAMS_DRY_RUN env var.

    Returns:
        dict with keys: ok, channel, target, status
    """
    effective_dry_run = _is_dry_run() if dry_run is None else dry_run

    title = f"Heron Alert — {service or target}" if (service or target) else "Heron Alert"

    if effective_dry_run:
        return {
            "ok": True, "channel": "teams", "target": target,
            "status": "dry_run", "message": message,
        }

    url = _webhook_url()
    if not url:
        return {
            "ok": False, "channel": "teams", "target": target,
            "status": "error", "error": "TEAMS_WEBHOOK_URL not configured",
            "message": message,
        }

    card = _adaptive_card(
        title=title, message=message, severity=severity,
        service=service, incident_id=incident_id, chronicle_url=chronicle_url,
    )

    try:
        resp = requests.post(url, json=card,
                             headers={"Content-Type": "application/json"}, timeout=10)
        resp.raise_for_status()
        return {
            "ok": True, "channel": "teams", "target": target,
            "status": "sent", "http_status": resp.status_code,
        }
    except Exception as exc:
        return {
            "ok": False, "channel": "teams", "target": target,
            "status": "error", "error": str(exc),
        }
