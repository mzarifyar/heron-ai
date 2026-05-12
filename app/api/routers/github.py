"""GitHub webhook receiver — correlates deployments with incidents.

Setup:
    1. In your GitHub repo: Settings → Webhooks → Add webhook
    2. Payload URL: https://your-heron-host/webhooks/github
    3. Content type: application/json
    4. Secret: set GITHUB_WEBHOOK_SECRET in .env (same value)
    5. Events: select "Pushes" and "Deployments" + "Deployment statuses"

Env vars:
    GITHUB_WEBHOOK_SECRET  — used to verify X-Hub-Signature-256
    GITHUB_DEFAULT_ENV     — default environment label if not in payload (default: production)
"""

from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from ...db.base import get_db
from ...db.models import GitDeployment
from ...core import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks/github", tags=["webhooks"])


# ── Signature verification ─────────────────────────────────────────────────

def _verify_signature(body: bytes, signature: str | None) -> None:
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "").strip()
    if not secret:
        return  # secret not configured — accept all (dev mode)
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256")
    expected = "sha256=" + hmac.new(
        secret.encode(), body, hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


# ── Service name extraction ────────────────────────────────────────────────

def _service_from_payload(payload: dict[str, Any], event: str) -> str:
    """Best-effort service name from GitHub payload.

    Priority:
    1. deployment.payload.service  (explicit from deployment API)
    2. repository.name             (repo name as service name)
    3. "unknown"
    """
    if event in ("deployment", "deployment_status"):
        dep = payload.get("deployment") or {}
        dep_payload = dep.get("payload") or {}
        if isinstance(dep_payload, dict) and dep_payload.get("service"):
            return str(dep_payload["service"])

    repo = payload.get("repository") or {}
    name = repo.get("name", "")
    # Strip common suffixes: -service, -api, -app
    for suffix in ("-service", "-api", "-app", "-backend", "-frontend"):
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name or "unknown"


# ── Event parsers ──────────────────────────────────────────────────────────

def _parse_push(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Parse a push event — only care about pushes to main/master/release."""
    ref = payload.get("ref", "")
    if not any(ref.endswith(b) for b in ("/main", "/master", "/release", "/prod", "/production")):
        return None  # ignore feature branches

    repo   = (payload.get("repository") or {}).get("full_name", "unknown/unknown")
    sha    = payload.get("after", "")[:40]
    pusher = (payload.get("pusher") or {}).get("name")
    head   = payload.get("head_commit") or {}
    msg    = (head.get("message") or "")[:500]
    ts_str = head.get("timestamp") or payload.get("created_at")

    return {
        "event": "push",
        "repo": repo,
        "ref": ref.removeprefix("refs/heads/"),
        "sha": sha,
        "environment": os.getenv("GITHUB_DEFAULT_ENV", "production"),
        "deployer": pusher,
        "status": "success",
        "commit_msg": msg,
        "deployed_at": _parse_ts(ts_str),
    }


def _parse_deployment(payload: dict[str, Any]) -> dict[str, Any] | None:
    dep    = payload.get("deployment") or {}
    repo   = (payload.get("repository") or {}).get("full_name", "unknown/unknown")
    env    = dep.get("environment") or os.getenv("GITHUB_DEFAULT_ENV", "production")
    sha    = dep.get("sha", "")[:40]
    ref    = dep.get("ref", "")
    deployer = (dep.get("creator") or {}).get("login")
    desc   = dep.get("description") or ""
    ts_str = dep.get("created_at")

    return {
        "event": "deployment",
        "repo": repo,
        "ref": ref,
        "sha": sha,
        "environment": env,
        "deployer": deployer,
        "status": "pending",
        "commit_msg": desc[:500] if desc else None,
        "deployed_at": _parse_ts(ts_str),
    }


def _parse_deployment_status(payload: dict[str, Any]) -> dict[str, Any] | None:
    ds     = payload.get("deployment_status") or {}
    dep    = payload.get("deployment") or {}
    repo   = (payload.get("repository") or {}).get("full_name", "unknown/unknown")
    state  = ds.get("state", "unknown")   # pending/success/failure/error/inactive
    sha    = dep.get("sha", "")[:40]
    ref    = dep.get("ref", "")
    env    = dep.get("environment") or os.getenv("GITHUB_DEFAULT_ENV", "production")
    deployer = (ds.get("creator") or {}).get("login")
    ts_str = ds.get("created_at")

    return {
        "event": "deployment_status",
        "repo": repo,
        "ref": ref,
        "sha": sha,
        "environment": env,
        "deployer": deployer,
        "status": state,
        "commit_msg": ds.get("description", "")[:500] or None,
        "deployed_at": _parse_ts(ts_str),
    }


def _parse_ts(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return datetime.now(timezone.utc).replace(tzinfo=None)


# ── Route ──────────────────────────────────────────────────────────────────

@router.post("")
async def receive_github_event(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict[str, Any]:
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    event = (x_github_event or "unknown").lower()
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    parsed: dict[str, Any] | None = None
    if event == "push":
        parsed = _parse_push(payload)
    elif event == "deployment":
        parsed = _parse_deployment(payload)
    elif event == "deployment_status":
        parsed = _parse_deployment_status(payload)
    elif event == "ping":
        return {"ok": True, "message": "pong"}

    if parsed is None:
        return {"ok": True, "message": f"event={event} ignored"}

    service = _service_from_payload(payload, event)
    dep = GitDeployment(
        id=str(uuid4()),
        service=service,
        repo=parsed["repo"],
        ref=parsed["ref"],
        sha=parsed["sha"],
        environment=parsed["environment"],
        deployer=parsed.get("deployer"),
        status=parsed["status"],
        commit_msg=parsed.get("commit_msg"),
        deployed_at=parsed["deployed_at"],
        raw_payload={"event": event, "action": payload.get("action")},
    )
    db.add(dep)
    db.commit()

    logger.info(
        "GitHub %s recorded: service=%s repo=%s sha=%s env=%s status=%s",
        event, service, parsed["repo"], parsed["sha"][:7],
        parsed["environment"], parsed["status"],
    )
    return {"ok": True, "id": dep.id, "service": service, "event": event}


# ── Correlation query (used by incident creation) ──────────────────────────

def find_preceding_deploys(
    db: Session,
    service: str,
    incident_time: datetime,
    lookback_minutes: int = 30,
) -> list[dict[str, Any]]:
    """Return deployments to `service` in the N minutes before `incident_time`."""
    from sqlalchemy import select
    window_start = datetime(
        incident_time.year, incident_time.month, incident_time.day,
        incident_time.hour, incident_time.minute, incident_time.second,
    ) - __import__("datetime").timedelta(minutes=lookback_minutes)

    rows = db.execute(
        select(GitDeployment)
        .where(
            GitDeployment.service == service,
            GitDeployment.deployed_at >= window_start,
            GitDeployment.deployed_at <= incident_time,
            GitDeployment.status.in_(["success", "pending"]),
        )
        .order_by(GitDeployment.deployed_at.desc())
        .limit(5)
    ).scalars().all()

    return [
        {
            "id": d.id,
            "repo": d.repo,
            "ref": d.ref,
            "sha": d.sha[:7],
            "environment": d.environment,
            "deployer": d.deployer,
            "deployed_at": d.deployed_at.isoformat(),
            "minutes_before_incident": round(
                (incident_time - d.deployed_at).total_seconds() / 60, 1
            ),
        }
        for d in rows
    ]
