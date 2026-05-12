"""AI insight generator — queries Chronicle, builds prompt, calls LLM, writes Recommendations.

Trigger:  POST /api/v1/intelligence/generate
Rate:     Once per hour maximum (enforced in-process; resets on restart).
Provider: Controlled by HERON_AI_PROVIDER / HERON_AI_API_KEY env vars.
          Defaults to claude-sonnet-4-6 via the Anthropic SDK with prompt caching.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)

# ── Rate limit ────────────────────────────────────────────────────────────────
_RATE_LIMIT_SECONDS = 3600
_last_run: datetime | None = None


def seconds_until_next_run() -> int:
    if _last_run is None:
        return 0
    elapsed = (datetime.utcnow() - _last_run).total_seconds()
    remaining = _RATE_LIMIT_SECONDS - elapsed
    return max(0, int(remaining))


# ── Context builders ──────────────────────────────────────────────────────────

def _incident_summary(db: Any, lookback_days: int) -> list[dict]:
    from sqlalchemy import func, select
    from ...db.models import Incident
    since = datetime.utcnow() - timedelta(days=lookback_days)
    rows = db.execute(
        select(
            Incident.service,
            func.count().label("total"),
            func.count().filter(Incident.auto_healed.is_(True)).label("healed"),
            func.avg(Incident.mttr_seconds).label("avg_mttr"),
        )
        .where(Incident.started_at >= since)
        .group_by(Incident.service)
        .order_by(func.count().desc())
    ).all()
    return [
        {
            "service": r.service,
            "incidents": int(r.total),
            "auto_healed": int(r.healed),
            "avg_mttr_seconds": round(float(r.avg_mttr or 0)),
        }
        for r in rows
    ]


def _outcome_history(db: Any, lookback_days: int) -> list[dict]:
    from sqlalchemy import case, func, select
    from ...db.models import LearnOutcome
    since = datetime.utcnow() - timedelta(days=lookback_days)
    rows = db.execute(
        select(
            LearnOutcome.action_type,
            LearnOutcome.service,
            func.count().label("cnt"),
            func.sum(case((LearnOutcome.outcome == "success", 1), else_=0)).label("wins"),
        )
        .where(LearnOutcome.recorded_at >= since)
        .group_by(LearnOutcome.action_type, LearnOutcome.service)
        .order_by(func.count().desc())
        .limit(40)
    ).all()
    return [
        {
            "action": r.action_type,
            "service": r.service,
            "attempts": int(r.cnt),
            "success_rate": round(r.wins / r.cnt, 2) if r.cnt else 0,
        }
        for r in rows
    ]


def _near_miss_summary(db: Any, lookback_days: int) -> list[dict]:
    from sqlalchemy import select
    from ...db.models import NearMiss
    since = datetime.utcnow() - timedelta(days=lookback_days)
    rows = db.execute(
        select(NearMiss)
        .where(NearMiss.detected_at >= since)
        .order_by(NearMiss.detected_at.desc())
        .limit(20)
    ).scalars().all()
    return [
        {
            "service": r.service,
            "metric": r.metric_name,
            "peak_value": round(r.peak_value, 3),
            "threshold": round(r.threshold, 3),
            "gap_percent": round(r.gap_percent, 1),
            "detected_at": r.detected_at.isoformat(),
        }
        for r in rows
    ]


def _load_policy() -> str:
    try:
        from pathlib import Path
        from app.core.paths import config as _cfg
        path = Path(_cfg("policy.yaml"))
        return path.read_text(encoding="utf-8") if path.exists() else "(policy not found)"
    except Exception:
        return "(policy not available)"


# ── Prompt ────────────────────────────────────────────────────────────────────

_SYSTEM = """You are Heron's intelligence engine. You analyse incident history, action outcome data, and near-miss signals for a software infrastructure team and return structured JSON insights.

Rules:
- Only reason from the data provided. Do not invent incidents or metrics.
- Be specific: name services, actions, and evidence.
- confidence is a float 0.0–1.0.
- Output ONLY valid JSON — no markdown fences, no prose outside the JSON object.
- If there is insufficient data for a section, return an empty array for that key."""

def _build_prompt(incidents: list, outcomes: list, near_misses: list, policy: str) -> str:
    return f"""Analyse the following Heron incident data and return a JSON object with three keys: recommendations, risks, patterns.

## Incident history (last 30 days)
{json.dumps(incidents, indent=2)}

## Action outcome history
{json.dumps(outcomes, indent=2)}

## Near-miss events
{json.dumps(near_misses, indent=2)}

## Current policy (policy.yaml excerpt)
{policy[:2000]}

## Output schema
Return exactly this JSON structure:
{{
  "recommendations": [
    {{
      "service": "service-name",
      "action": "action_type",
      "confidence": 0.0,
      "rationale": "why this action for this service, citing evidence",
      "suggested_policy_change": "optional: what to change in policy.yaml"
    }}
  ],
  "risks": [
    {{
      "service": "service-name",
      "risk": "description of the risk",
      "recommended_action": "what to do about it"
    }}
  ],
  "patterns": [
    {{
      "pattern": "description of a recurring pattern across services or time",
      "confidence": 0.0,
      "suggested_action": "what the team should do"
    }}
  ]
}}"""


# ── Parser ────────────────────────────────────────────────────────────────────

def _parse_response(text: str) -> dict[str, list]:
    text = text.strip()
    # Strip markdown fences if the model added them despite instructions
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            if part.startswith("json"):
                part = part[4:]
            part = part.strip()
            if part.startswith("{"):
                text = part
                break

    # Try parsing as-is first
    try:
        parsed = json.loads(text)
        return {
            "recommendations": parsed.get("recommendations", []),
            "risks":           parsed.get("risks", []),
            "patterns":        parsed.get("patterns", []),
        }
    except json.JSONDecodeError:
        pass

    # Extract the outermost JSON object by brace matching (handles truncated responses)
    try:
        start = text.index("{")
        depth, end = 0, start
        for i, ch in enumerate(text[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        parsed = json.loads(text[start:end + 1])
        return {
            "recommendations": parsed.get("recommendations", []),
            "risks":           parsed.get("risks", []),
            "patterns":        parsed.get("patterns", []),
        }
    except Exception as exc:
        logger.warning("Failed to parse LLM response as JSON: %s\nResponse: %.300s", exc, text)
        return {"recommendations": [], "risks": [], "patterns": []}


# ── DB write ──────────────────────────────────────────────────────────────────

def _persist(db: Any, parsed: dict[str, list]) -> int:
    from ...db.models import Recommendation
    count = 0
    now = datetime.utcnow()

    for rec in parsed.get("recommendations", []):
        service = str(rec.get("service", "unknown"))
        action  = str(rec.get("action", "unknown"))
        conf    = float(rec.get("confidence", 0.5))
        rationale = str(rec.get("rationale", ""))
        if rec.get("suggested_policy_change"):
            rationale += f"\n\nSuggested policy change: {rec['suggested_policy_change']}"
        db.add(Recommendation(
            id=str(uuid4()), service=service, action_type=action,
            confidence=round(conf, 3), rationale=rationale,
            status="pending", created_at=now,
        ))
        count += 1

    for risk in parsed.get("risks", []):
        service = str(risk.get("service", "unknown"))
        rationale = f"Risk: {risk.get('risk', '')}\nRecommended action: {risk.get('recommended_action', '')}"
        db.add(Recommendation(
            id=str(uuid4()), service=service, action_type="risk_flag",
            confidence=0.75, rationale=rationale,
            status="pending", created_at=now,
        ))
        count += 1

    for pat in parsed.get("patterns", []):
        rationale = f"Pattern: {pat.get('pattern', '')}\nSuggested action: {pat.get('suggested_action', '')}"
        db.add(Recommendation(
            id=str(uuid4()), service="*", action_type="pattern",
            confidence=float(pat.get("confidence", 0.5)),
            rationale=rationale, status="pending", created_at=now,
        ))
        count += 1

    db.commit()
    return count


# ── Public entry point ────────────────────────────────────────────────────────

def generate_insights(lookback_days: int = 30) -> dict[str, Any]:
    """Query Chronicle, call the LLM, persist results, return a summary.

    Returns a dict with keys: ok, provider, model, generated, insights, error.
    """
    global _last_run

    from .provider import get_ai_provider
    from ...db.base import SessionLocal

    provider = get_ai_provider()
    if not provider:
        return {
            "ok": False,
            "error": "No AI provider configured. Set HERON_AI_PROVIDER and HERON_AI_API_KEY.",
        }
    # Insight responses can be large — override the default max_tokens for this call
    provider.max_tokens = 4096

    with SessionLocal() as db:
        incidents   = _incident_summary(db, lookback_days)
        outcomes    = _outcome_history(db, lookback_days)
        near_misses = _near_miss_summary(db, lookback_days)

    policy = _load_policy()
    prompt = _build_prompt(incidents, outcomes, near_misses, policy)

    logger.info(
        "Generating AI insights — provider=%s model=%s incidents=%d outcomes=%d near_misses=%d",
        provider.provider, provider.model, len(incidents), len(outcomes), len(near_misses),
    )

    try:
        raw = provider.complete(prompt, system=_SYSTEM)
    except Exception as exc:
        logger.error("LLM call failed: %s", exc)
        return {"ok": False, "error": str(exc)}

    parsed = _parse_response(raw)

    # Clear existing AI-generated pending rows before writing new ones
    with SessionLocal() as db:
        from ...db.models import Recommendation
        db.query(Recommendation).filter(
            Recommendation.status == "pending",
            Recommendation.action_type.in_(["risk_flag", "pattern"]),
        ).delete()
        db.commit()

        count = _persist(db, parsed)

    _last_run = datetime.utcnow()
    logger.info("AI insights generated: %d recommendations written", count)

    return {
        "ok": True,
        "provider": provider.provider,
        "model": provider.model,
        "generated": count,
        "insights": parsed,
    }
