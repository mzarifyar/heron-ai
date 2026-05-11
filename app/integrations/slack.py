"""Slack integration — posts escalation messages via Incoming Webhooks."""

from __future__ import annotations

import json
import os
from typing import Dict

import requests


def _webhook_url() -> str:
    return os.getenv("SLACK_WEBHOOK_URL", "").strip()


def _is_dry_run() -> bool:
    raw = os.getenv("SLACK_DRY_RUN", "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def send_message(*, target: str, message: str, dry_run: bool | None = None) -> Dict[str, object]:
    """Send a message to Slack via Incoming Webhook.

    Args:
        target:  Channel name or identifier (used as context, not re-routed —
                 the webhook is already bound to a channel in Slack's settings).
        message: Plain-text or mrkdwn-formatted message body.
        dry_run: Override the SLACK_DRY_RUN env flag.  None = read from env.

    Returns:
        dict with keys: ok, channel, target, status, message
    """
    effective_dry_run = _is_dry_run() if dry_run is None else dry_run

    if effective_dry_run:
        return {
            "ok": True, "channel": "slack", "target": target,
            "status": "dry_run", "message": message,
        }

    url = _webhook_url()
    if not url:
        return {
            "ok": False, "channel": "slack", "target": target,
            "status": "error", "error": "SLACK_WEBHOOK_URL not configured",
            "message": message,
        }

    payload = {
        "text": message,
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": message},
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"*Heron* — channel: {target}"},
                ],
            },
        ],
    }

    try:
        resp = requests.post(
            url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        return {
            "ok": True, "channel": "slack", "target": target,
            "status": "sent", "http_status": resp.status_code,
            "message": message,
        }
    except Exception as exc:
        return {
            "ok": False, "channel": "slack", "target": target,
            "status": "error", "error": str(exc),
            "message": message,
        }
