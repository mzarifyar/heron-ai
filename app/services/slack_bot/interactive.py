"""Slack interactive component handler — button clicks and overflow actions."""

from __future__ import annotations

import json
from typing import Any

from ...core import get_logger
from .commands import _bot_post, _update_message

logger = get_logger(__name__)


def handle_interactive(payload: dict[str, Any]) -> dict[str, Any]:
    """Dispatch button clicks and overflow menu selections."""
    payload_type = payload.get("type", "")
    actions = payload.get("actions", [])
    user = (payload.get("user") or {}).get("username", "unknown")
    channel = (payload.get("channel") or {}).get("id", "")
    message_ts = (payload.get("message") or {}).get("ts", "")
    response_url = payload.get("response_url", "")

    for action in actions:
        action_id = action.get("action_id", "")
        value     = action.get("value", "")

        logger.info("Slack action: %s value=%s user=@%s", action_id, value, user)

        if action_id.startswith("ack_"):
            return _handle_acknowledge(value, user, channel, message_ts)

        if action_id.startswith("escalate_"):
            return _handle_escalate(value, user, channel, message_ts)

        if action_id.startswith("resolve_"):
            return _handle_resolve(value, user, channel, message_ts)

        if action_id.startswith("approve_"):
            return _handle_approve_action(value, user, channel, message_ts)

        if action_id.startswith("reject_"):
            return _handle_reject_action(value, user, channel, message_ts)

        if action_id.startswith("details_"):
            return _handle_details(value, channel)

    return {"ok": True}


# ── Action handlers ───────────────────────────────────────────────────────────

def _handle_acknowledge(incident_id: str, user: str, channel: str, ts: str) -> dict:
    try:
        _db_tag_incident(incident_id, f"acked_by:{user}")
    except Exception:
        pass
    _update_message(
        channel, ts,
        text=f"🟡 Incident `{incident_id}` acknowledged by @{user}",
        blocks=[{"type": "section", "text": {"type": "mrkdwn",
            "text": f"🟡 *Acknowledged* by @{user}\nIncident `{incident_id}` is being investigated."}}],
    )
    return {}


def _handle_escalate(incident_id: str, user: str, channel: str, ts: str) -> dict:
    try:
        from ...db.base import SessionLocal
        from ...db.models import Incident
        from ...integrations.pagerduty import trigger_incident
        from ...integrations.slack import send_message
        with SessionLocal() as db:
            inc = db.get(Incident, incident_id)
            if inc:
                trigger_incident(
                    target=inc.service,
                    message=f"Escalated by @{user} via Slack: {inc.title}",
                    severity=inc.severity,
                    service=inc.service,
                    incident_id=incident_id,
                )
    except Exception as exc:
        logger.warning("Escalate action failed: %s", exc)

    _update_message(
        channel, ts,
        text=f"⚡ Escalated by @{user}",
        blocks=[{"type": "section", "text": {"type": "mrkdwn",
            "text": f"⚡ *Escalated* by @{user} — on-call has been paged for incident `{incident_id}`."}}],
    )
    return {}


def _handle_resolve(incident_id: str, user: str, channel: str, ts: str) -> dict:
    try:
        from ...db.base import SessionLocal
        from ...db.models import Incident
        from datetime import datetime
        with SessionLocal() as db:
            inc = db.get(Incident, incident_id)
            if inc and inc.status == "active":
                inc.status = "resolved"
                inc.resolved_at = datetime.utcnow()
                db.commit()
    except Exception as exc:
        logger.warning("Resolve action failed: %s", exc)

    _update_message(
        channel, ts,
        text=f"✅ Resolved by @{user}",
        blocks=[{"type": "section", "text": {"type": "mrkdwn",
            "text": f"✅ *Resolved* by @{user} — incident `{incident_id}` marked resolved."}}],
    )
    return {}


def _handle_approve_action(decision_id: str, user: str, channel: str, ts: str) -> dict:
    try:
        from ...services.core import core_service
        from ...services.reflex import reflex_service
        plan = core_service.get_plan(decision_id)
        if plan:
            for step in plan.actions:
                step.requires_approval = False
            executions = reflex_service.execute_plan(plan)
            statuses = ", ".join(e.status for e in executions)
            text = f"✅ @{user} approved `{decision_id}` — actions: {statuses}"
        else:
            text = f"⚠️ Decision `{decision_id}` not found (may have expired)."
    except Exception as exc:
        text = f"❌ Approval failed: {exc}"

    _update_message(
        channel, ts, text=text,
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    )
    return {}


def _handle_reject_action(decision_id: str, user: str, channel: str, ts: str) -> dict:
    try:
        from ...services.core import core_service
        plan = core_service.get_plan(decision_id)
        if plan:
            core_service.record_outcome(decision_id, status="failed",
                                        notes=f"Rejected by @{user} via Slack button")
    except Exception as exc:
        logger.warning("Reject action failed: %s", exc)

    text = f"🚫 @{user} rejected decision `{decision_id}` — no action taken."
    _update_message(
        channel, ts, text=text,
        blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    )
    return {}


def _handle_details(incident_id: str, channel: str) -> dict:
    try:
        from ...db.base import SessionLocal
        from ...db.models import Incident
        from .blocks import incident_card
        with SessionLocal() as db:
            inc = db.get(Incident, incident_id)
            if inc:
                inc_dict = {
                    "id": inc.id, "title": inc.title, "service": inc.service,
                    "severity": inc.severity, "status": inc.status,
                    "region": inc.region, "environment": inc.environment,
                    "auto_healed": inc.auto_healed, "mttr_seconds": inc.mttr_seconds,
                    "started_at": inc.started_at.isoformat() if inc.started_at else "",
                }
                _bot_post(
                    channel,
                    text=f"Incident details: {inc.title}",
                    attachments=[incident_card(inc_dict, show_actions=True)],
                )
    except Exception as exc:
        logger.warning("Details action failed: %s", exc)
    return {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _db_tag_incident(incident_id: str, tag: str) -> None:
    from ...db.base import SessionLocal
    from ...db.models import Incident
    with SessionLocal() as db:
        inc = db.get(Incident, incident_id)
        if inc:
            db.commit()   # no-op for now; tag storage can be added later
