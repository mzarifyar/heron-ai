"""Slack Block Kit message builders — incident cards, status panels, help text."""

from __future__ import annotations

from typing import Any


# ── Colour mapping ─────────────────────────────────────────────────────────────
# Slack sidebar colours (attachment fallback — Block Kit doesn't support native colour)
_SEV_COLOUR = {
    "sev1": "#f43f5e",   # rose
    "sev2": "#f97316",   # orange
    "sev3": "#f59e0b",   # amber
    "sev4": "#6b7280",   # gray
    "info": "#6b7280",
}

_STATUS_EMOJI = {
    "active":    "🔴",
    "resolved":  "✅",
    "escalated": "⚠️",
}


# ── Incident card ──────────────────────────────────────────────────────────────

def incident_card(inc: dict[str, Any], *, show_actions: bool = True) -> dict[str, Any]:
    """Full incident Block Kit card with Approve / Escalate / Acknowledge buttons."""
    iid      = inc.get("id", "unknown")
    title    = inc.get("title", "Untitled incident")
    svc      = inc.get("service", "unknown")
    sev      = inc.get("severity", "sev3")
    status   = inc.get("status", "active")
    region   = inc.get("region", "")
    env      = inc.get("environment", "")
    healed   = inc.get("auto_healed", False)
    mttr     = inc.get("mttr_seconds")
    started  = inc.get("started_at", "")[:19].replace("T", " ") if inc.get("started_at") else "—"
    colour   = _SEV_COLOUR.get(sev, "#6b7280")
    s_emoji  = _STATUS_EMOJI.get(status, "❓")

    meta_parts = [f"*Service:* {svc}", f"*Severity:* `{sev}`", f"*Status:* {s_emoji} {status}"]
    if region:
        meta_parts.append(f"*Region:* {region}")
    if env:
        meta_parts.append(f"*Env:* {env}")
    if healed and mttr:
        mins = mttr // 60
        secs = mttr % 60
        meta_parts.append(f"*MTTR:* {f'{mins}m {secs}s' if mins else f'{secs}s'} (auto-healed ✓)")

    blocks: list[dict] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*{title}*\n{chr(10).join(meta_parts)}"},
            "accessory": {
                "type": "overflow",
                "options": [
                    {"text": {"type": "plain_text", "text": "View in Chronicle"}, "value": f"view_chronicle_{iid}"},
                    {"text": {"type": "plain_text", "text": "Copy incident ID"}, "value": f"copy_id_{iid}"},
                ],
                "action_id": f"overflow_{iid}",
            },
        },
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"ID: `{iid}` · Started: {started}"}]},
    ]

    if show_actions and status == "active":
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✓ Acknowledge"},
                    "style": "primary",
                    "value": iid,
                    "action_id": f"ack_{iid}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "⚡ Escalate"},
                    "style": "danger",
                    "value": iid,
                    "action_id": f"escalate_{iid}",
                    "confirm": {
                        "title": {"type": "plain_text", "text": "Escalate incident?"},
                        "text": {"type": "mrkdwn", "text": f"This will page on-call for `{svc}`."},
                        "confirm": {"type": "plain_text", "text": "Yes, page on-call"},
                        "deny": {"type": "plain_text", "text": "Cancel"},
                    },
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✓ Mark resolved"},
                    "value": iid,
                    "action_id": f"resolve_{iid}",
                },
            ],
        })

    return {
        "color": colour,
        "blocks": blocks,
    }


# ── Status summary ─────────────────────────────────────────────────────────────

def status_summary(incidents: list[dict], *, total_this_week: int = 0, success_rate: float = 0) -> list[dict]:
    """Compact status panel for /heron status."""
    active   = [i for i in incidents if i.get("status") == "active"]
    resolved = [i for i in incidents if i.get("status") == "resolved"]

    if not active:
        header = "✅ *All systems nominal* — no active incidents"
    else:
        header = f"🔴 *{len(active)} active incident{'s' if len(active) > 1 else ''}*"

    blocks: list[dict] = [
        {"type": "header", "text": {"type": "plain_text", "text": "Heron Status"}},
        {"type": "section",  "text": {"type": "mrkdwn", "text": header}},
    ]

    if active:
        blocks.append({"type": "divider"})
        for inc in active[:5]:
            sev = inc.get("severity", "sev3")
            svc = inc.get("service", "?")
            t   = inc.get("title", "Untitled")[:60]
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"`{sev}` *{svc}* — {t}"},
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Details"},
                    "value": inc.get("id", ""),
                    "action_id": f"details_{inc.get('id', '')}",
                },
            })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": (
                f"📊 This week: *{total_this_week}* incidents · "
                f"Auto-heal rate: *{success_rate * 100:.0f}%* · "
                f"Resolved this session: *{len(resolved)}*"
            ),
        }],
    })

    return blocks


# ── Approve confirmation ───────────────────────────────────────────────────────

def approval_card(decision_id: str, action: str, service: str, rationale: str) -> list[dict]:
    """Interactive card asking for human approval of a pending Heron action."""
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "⏳ Heron Action — Awaiting Approval"}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": (
                f"*Action:* `{action}` on *{service}*\n"
                f"*Rationale:* {rationale[:300]}"
            )},
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✓ Approve"},
                    "style": "primary",
                    "value": decision_id,
                    "action_id": f"approve_{decision_id}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✗ Reject"},
                    "style": "danger",
                    "value": decision_id,
                    "action_id": f"reject_{decision_id}",
                },
            ],
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"Decision ID: `{decision_id}`"}],
        },
    ]


# ── Help text ──────────────────────────────────────────────────────────────────

def help_blocks() -> list[dict]:
    return [
        {"type": "header", "text": {"type": "plain_text", "text": "Heron — Slash Commands"}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": (
                "*`/heron status`*\nCurrent active incidents and this week's summary\n\n"
                "*`/heron incidents`*\nLast 5 incidents across all services\n\n"
                "*`/heron approve <decision_id>`*\nApprove a pending autonomous action\n\n"
                "*`/heron reject <decision_id>`*\nReject a pending autonomous action\n\n"
                "*`/heron help`*\nShow this message"
            )},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": "Heron — Autonomous incident intelligence · heron-ai.net"}],
        },
    ]
