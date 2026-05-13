"""Slack request signature verification.

Every incoming Slack payload must be verified using the signing secret
to prevent spoofed requests.  Slack signs all requests with HMAC-SHA256.

Env vars:
    SLACK_SIGNING_SECRET = abc123...  (from Slack App → Basic Information)
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time

from fastapi import HTTPException, Request


async def verify_slack_request(request: Request) -> bytes:
    """Verify X-Slack-Signature and return the raw body.

    Raises HTTP 401 if signing secret not configured or signature invalid.
    Raises HTTP 408 if timestamp is too old (replay protection).
    Returns the raw body bytes for downstream parsing.
    """
    secret = os.getenv("SLACK_SIGNING_SECRET", "").strip()
    body   = await request.body()

    if not secret:
        # Dev mode — accept without verification but warn
        import logging
        logging.getLogger(__name__).warning(
            "SLACK_SIGNING_SECRET not set — accepting Slack request without verification"
        )
        return body

    timestamp = request.headers.get("X-Slack-Request-Timestamp", "")
    signature = request.headers.get("X-Slack-Signature", "")

    # Replay protection: reject requests older than 5 minutes
    try:
        if abs(time.time() - int(timestamp)) > 300:
            raise HTTPException(status_code=408, detail="Request timestamp too old")
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="Invalid timestamp")

    base = f"v0:{timestamp}:{body.decode('utf-8', errors='replace')}"
    expected = "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    return body
