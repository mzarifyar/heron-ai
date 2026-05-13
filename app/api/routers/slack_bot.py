"""Slack bot HTTP endpoints.

Setup:
    1. Create a Slack App at api.slack.com/apps
    2. Add a slash command /heron → URL: https://your-heron-host/slack/commands
    3. Enable Interactivity → URL: https://your-heron-host/slack/interactive
    4. Add bot scopes: commands, chat:write, chat:write.public
    5. Install to workspace, copy Bot Token (xoxb-...)
    6. Set env vars:
           SLACK_BOT_TOKEN=xoxb-...
           SLACK_SIGNING_SECRET=...    (Basic Information → Signing Secret)
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...core import get_logger
from ...services.slack_bot.verify import verify_slack_request
from ...services.slack_bot.commands import handle_command
from ...services.slack_bot.interactive import handle_interactive

logger = get_logger(__name__)
router = APIRouter(prefix="/slack", tags=["slack-bot"])


# ── URL verification (Slack sends a challenge on first setup) ──────────────────

@router.post("/events")
async def slack_events(request: Request) -> JSONResponse:
    """Handle Slack Events API — currently used for URL verification only."""
    body = await verify_slack_request(request)
    try:
        data = json.loads(body)
    except Exception:
        return JSONResponse({"error": "invalid json"}, status_code=400)

    if data.get("type") == "url_verification":
        return JSONResponse({"challenge": data.get("challenge")})

    # Future: handle event callbacks here
    return JSONResponse({"ok": True})


# ── Slash commands ─────────────────────────────────────────────────────────────

@router.post("/commands")
async def slack_commands(request: Request) -> JSONResponse:
    """Receive /heron slash commands."""
    body = await verify_slack_request(request)

    # Slack sends slash command payloads as application/x-www-form-urlencoded
    try:
        form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        payload = {k: v[0] for k, v in form.items()}
    except Exception:
        return JSONResponse({"error": "invalid payload"}, status_code=400)

    response = handle_command(payload)
    return JSONResponse(response)


# ── Interactive components ─────────────────────────────────────────────────────

@router.post("/interactive")
async def slack_interactive(request: Request) -> JSONResponse:
    """Receive button clicks and overflow menu actions."""
    body = await verify_slack_request(request)

    # Interactive payloads arrive as payload=<json> in form data
    try:
        form = parse_qs(body.decode("utf-8"), keep_blank_values=True)
        payload_str = (form.get("payload") or ["{}"])[0]
        payload = json.loads(payload_str)
    except Exception as exc:
        logger.warning("Failed to parse interactive payload: %s", exc)
        return JSONResponse({"error": "invalid payload"}, status_code=400)

    result = handle_interactive(payload)

    # Return empty 200 to acknowledge immediately (Slack requires < 3s)
    return JSONResponse(result or {})
