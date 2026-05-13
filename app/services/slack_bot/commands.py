"""Slack slash command handlers — /heron <subcommand>."""

from __future__ import annotations

import os
from typing import Any

import requests

from ...core import get_logger
from .blocks import approval_card, help_blocks, incident_card, status_summary

logger = get_logger(__name__)

_BOT_TOKEN = lambda: os.getenv("SLACK_BOT_TOKEN", "").strip()  # noqa: E731


def _post_to_slack(response_url: str, payload: dict[str, Any]) -> None:
    """Post a delayed response to Slack via the response_url (valid for 30 min)."""
    try:
        requests.post(response_url, json=payload, timeout=10)
    except Exception as exc:
        logger.warning("Slack response_url post failed: %s", exc)


def _bot_post(channel: str, text: str, blocks: list | None = None, attachments: list | None = None) -> None:
    """Post a message to a channel using the Bot Token."""
    token = _BOT_TOKEN()
    if not token:
        logger.warning("SLACK_BOT_TOKEN not set — cannot post to channel")
        return
    payload: dict[str, Any] = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    if attachments:
        payload["attachments"] = attachments
    try:
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        body = resp.json()
        if not body.get("ok"):
            logger.warning("Slack postMessage failed: %s", body.get("error"))
    except Exception as exc:
        logger.warning("Slack postMessage error: %s", exc)


def _update_message(channel: str, ts: str, text: str, blocks: list | None = None) -> None:
    """Update an existing Slack message (for button response updates)."""
    token = _BOT_TOKEN()
    if not token:
        return
    payload: dict[str, Any] = {"channel": channel, "ts": ts, "text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        requests.post(
            "https://slack.com/api/chat.update",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
    except Exception as exc:
        logger.warning("Slack chat.update error: %s", exc)


# ── DB queries ────────────────────────────────────────────────────────────────

def _get_incidents(limit: int = 5, active_only: bool = False) -> tuple[list[dict], int, float]:
    """Return (incidents, total_this_week, success_rate)."""
    try:
        from ...db.base import SessionLocal
        from ...db.models import Incident
        from ...db.repositories import get_learn_summary
        from sqlalchemy import select
        from datetime import datetime, timedelta

        with SessionLocal() as db:
            q = select(Incident).order_by(Incident.started_at.desc())
            if active_only:
                q = q.where(Incident.status == "active")
            rows = db.execute(q.limit(limit)).scalars().all()
            incidents = [
                {
                    "id": r.id, "title": r.title, "service": r.service,
                    "severity": r.severity, "status": r.status,
                    "region": r.region, "environment": r.environment,
                    "auto_healed": r.auto_healed, "mttr_seconds": r.mttr_seconds,
                    "started_at": r.started_at.isoformat() if r.started_at else "",
                }
                for r in rows
            ]
            summary = get_learn_summary(db)
            return incidents, summary.get("total_outcomes", 0), summary.get("success_rate", 0.0)
    except Exception as exc:
        logger.warning("DB query failed in Slack command: %s", exc)
        return [], 0, 0.0


# ── Command dispatcher ────────────────────────────────────────────────────────

def handle_command(payload: dict[str, Any]) -> dict[str, Any]:
    """Parse and dispatch a /heron slash command.

    Returns an immediate Slack response (must be within 3 seconds).
    Heavy work is done asynchronously via response_url.
    """
    text         = (payload.get("text") or "").strip()
    response_url = payload.get("response_url", "")
    channel_id   = payload.get("channel_id", "")
    user_name    = payload.get("user_name", "unknown")

    parts   = text.split(None, 1)
    command = parts[0].lower() if parts else "status"
    args    = parts[1].strip() if len(parts) > 1 else ""

    logger.info("/heron %s from @%s in %s", command, user_name, channel_id)

    if command in ("status", ""):
        return _cmd_status(response_url)

    if command == "incidents":
        return _cmd_incidents(response_url)

    if command == "approve":
        return _cmd_approve(args, user_name, response_url)

    if command == "reject":
        return _cmd_reject(args, user_name, response_url)

    if command == "help":
        return {"response_type": "ephemeral", "blocks": help_blocks()}

    return {
        "response_type": "ephemeral",
        "text": f"Unknown command: `{command}`. Try `/heron help`.",
    }


# ── Individual command handlers ───────────────────────────────────────────────

def _cmd_status(response_url: str) -> dict[str, Any]:
    incidents, total_week, rate = _get_incidents(limit=10)
    active = [i for i in incidents if i.get("status") == "active"]
    blocks = status_summary(incidents, total_this_week=total_week, success_rate=rate)

    if response_url and active:
        # Post active incident cards as a follow-up
        attachments = [incident_card(i, show_actions=True) for i in active[:3]]
        _post_to_slack(response_url, {
            "response_type": "in_channel",
            "text": f"{'🔴 ' + str(len(active)) + ' active incident(s)' if active else '✅ All clear'}",
            "blocks": blocks,
            "attachments": attachments,
        })
        return {"response_type": "in_channel", "text": "Fetching status…"}

    return {"response_type": "in_channel", "blocks": blocks}


def _cmd_incidents(response_url: str) -> dict[str, Any]:
    incidents, _, _ = _get_incidents(limit=5)
    if not incidents:
        return {"response_type": "ephemeral", "text": "No incidents found."}

    attachments = [incident_card(i, show_actions=True) for i in incidents]
    return {
        "response_type": "in_channel",
        "text": f"Last {len(incidents)} incidents:",
        "attachments": attachments,
    }


def _cmd_approve(decision_id: str, user_name: str, response_url: str) -> dict[str, Any]:
    if not decision_id:
        return {"response_type": "ephemeral", "text": "Usage: `/heron approve <decision_id>`"}

    try:
        from ...services.core import core_service
        plan = core_service.get_plan(decision_id)
        if plan is None:
            return {
                "response_type": "ephemeral",
                "text": f"Decision `{decision_id}` not found. It may have expired (in-memory only).",
            }

        # Flip requires_approval=False on all steps and execute
        from ...services.reflex import reflex_service
        for step in plan.actions:
            step.requires_approval = False
        executions = reflex_service.execute_plan(plan)
        statuses = [e.status for e in executions]

        if response_url:
            _post_to_slack(response_url, {
                "response_type": "in_channel",
                "text": (
                    f"✅ @{user_name} approved `{decision_id}` — "
                    f"{len(executions)} action(s): {', '.join(statuses)}"
                ),
            })
        return {"response_type": "in_channel", "text": f"Approving `{decision_id}`…"}

    except Exception as exc:
        logger.error("Approve command failed: %s", exc)
        return {"response_type": "ephemeral", "text": f"Approval failed: {exc}"}


def _cmd_reject(decision_id: str, user_name: str, response_url: str) -> dict[str, Any]:
    if not decision_id:
        return {"response_type": "ephemeral", "text": "Usage: `/heron reject <decision_id>`"}

    try:
        from ...services.core import core_service
        plan = core_service.get_plan(decision_id)
        if plan is None:
            return {"response_type": "ephemeral", "text": f"Decision `{decision_id}` not found."}

        # Record outcome as rejected (observe_only override)
        core_service.record_outcome(
            decision_id, status="failed",
            notes=f"Rejected by @{user_name} via Slack"
        )
        return {
            "response_type": "in_channel",
            "text": f"🚫 @{user_name} rejected decision `{decision_id}` — no action will be taken.",
        }
    except Exception as exc:
        return {"response_type": "ephemeral", "text": f"Rejection failed: {exc}"}
