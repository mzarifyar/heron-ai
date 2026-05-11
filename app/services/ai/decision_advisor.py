"""LLM-powered decision advisor — the brain of Heron's Decide step.

Replaces the rule-based _build_steps() in core.py with a Claude (or OpenAI)
call that reasons over incident context, Chronicle history, and Learn scores
to produce a ranked, explained action plan.

Falls back to rule-based decisions if:
  - HERON_AI_PROVIDER is not configured
  - The API call fails (network, auth, quota)
  - The response cannot be parsed into the required schema
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any, Optional

from ...core import get_logger
from ...schemas.anomaly import Anomaly
from ...schemas.decision import DecisionStep
from ...schemas.signal import BufferedSignal
from .provider import get_ai_provider
from .context_builder import build_context

logger = get_logger(__name__)

# ── System prompt (cached by Anthropic's prompt caching) ──────────────────

SYSTEM_PROMPT = """You are Heron's autonomous incident decision engine.

Your job: analyse an infrastructure incident and select the optimal remediation
actions. You reason over the triggering signal, recent metric history, past
incident outcomes, action confidence scores, and policy constraints.

Rules:
1. Output ONLY valid JSON — no preamble, no markdown fences, no explanation outside the JSON.
2. Choose actions that have high historical success rates for this service.
3. Prefer actions that do not require human approval for sev2/sev3.
4. For sev1, set escalate_immediately=true unless confidence > 0.85.
5. Confidence should reflect genuine certainty based on evidence, not wishful thinking.
6. reasoning should be 2-4 sentences explaining WHY this action was chosen over alternatives.

Output schema (respond ONLY with this JSON, nothing else):
{
  "reasoning": "string — 2-4 sentences explaining the decision",
  "steps": [
    {
      "action": "string — must be from available_actions",
      "rationale": "string — one sentence specific to this action",
      "priority": 1,
      "requires_approval": false,
      "parameters": {"key": "value"}
    }
  ],
  "confidence": 0.0,
  "escalate_immediately": false,
  "escalate_reason": null
}"""


def _build_prompt(ctx: dict[str, Any]) -> str:
    inc  = ctx["incident"]
    sigs = ctx["recent_signals"]
    hist = ctx["chronicle_history"]
    learn = ctx["learn_scores"]
    policy = ctx["policy_summary"]
    actions = ctx["available_actions"]

    sig_lines = "\n".join(
        f"  {s['timestamp'][-8:]}  {s['metric']}={s['value']}  [{s['severity']}]"
        for s in sigs[:10]
    ) or "  (no recent signals)"

    hist_lines = ""
    for h in hist[:5]:
        healed = "✓ auto-healed" if h.get("auto_healed") else "✗ manual"
        mttr = f"{h['mttr_seconds']//60}m" if h.get("mttr_seconds") else "unknown"
        hist_lines += f"\n  [{h['severity']}] {h['title'][:80]}"
        hist_lines += f"\n    → {healed} in {mttr}"
        for ev in h.get("key_events", [])[:2]:
            hist_lines += f"\n    · {ev['type']}: {ev['desc'][:100]}"
    if not hist_lines:
        hist_lines = "\n  (no recent incidents for this service)"

    learn_lines = "\n".join(
        f"  {s.get('action','?')}: {s.get('success_rate',0)*100:.0f}% success "
        f"({s.get('total',0)} runs, service={s.get('service','global')})"
        for s in learn[:6]
    ) or "  (no outcome history yet — use conservative defaults)"

    return f"""## Incident
Service:     {inc['service']}
Severity:    {inc['severity']}
Region:      {inc['region']}
Environment: {inc['environment']}
Signal:      {inc['metric_name']} = {inc['observed_value']} (threshold: {inc['threshold']})
Summary:     {inc['summary']}

## Recent Signals (last 30 min)
{sig_lines}

## Chronicle History (this service, last 90 days)
{hist_lines}

## Action Confidence Scores (Learn loop)
{learn_lines}

## Available Actions
{json.dumps(actions, indent=2)}

## Policy Constraints
{policy}

Respond with JSON only."""


def _parse_response(text: str) -> Optional[dict[str, Any]]:
    """Extract and validate JSON from the LLM response."""
    # Strip markdown code fences if present
    text = re.sub(r"```(?:json)?\s*", "", text).strip()
    text = re.sub(r"```\s*$", "", text).strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Try to find JSON object in the response
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if not match:
            logger.warning("LLM response is not valid JSON")
            return None
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            logger.warning("Could not parse JSON from LLM response")
            return None

    # Validate required keys
    required = {"reasoning", "steps", "confidence", "escalate_immediately"}
    if not required.issubset(data.keys()):
        logger.warning("LLM response missing required keys: %s",
                       required - set(data.keys()))
        return None

    if not isinstance(data["steps"], list) or not data["steps"]:
        logger.warning("LLM response has empty or invalid steps")
        return None

    return data


def _to_decision_steps(
    parsed: dict[str, Any], service: str
) -> list[DecisionStep]:
    """Convert parsed LLM output into DecisionStep objects."""
    steps = []
    for i, raw in enumerate(parsed.get("steps", [])[:5]):
        if not isinstance(raw, dict):
            continue
        action = str(raw.get("action", "observe_only")).strip()
        steps.append(
            DecisionStep(
                action=action,
                rationale=str(raw.get("rationale", "AI-selected action"))[:500],
                priority=int(raw.get("priority", i + 1)),
                requires_approval=bool(raw.get("requires_approval", False)),
                parameters={
                    "service": service,
                    **{k: v for k, v in (raw.get("parameters") or {}).items()
                       if isinstance(k, str)},
                },
            )
        )
    return steps or [
        DecisionStep(
            action="observe_only",
            rationale="LLM returned no actionable steps",
            priority=1,
            requires_approval=False,
            parameters={"service": service},
        )
    ]


class DecisionAdvisor:
    """LLM-powered decision advisor — drop-in replacement for rule-based _build_steps."""

    def advise(
        self,
        *,
        anomalies: list[Anomaly],
        buffered_signal: BufferedSignal,
        severity: str,
        learn_scores: dict[str, Any],
    ) -> Optional[tuple[list[DecisionStep], float, str, bool]]:
        """Ask the LLM for a decision plan.

        Returns:
            (steps, confidence, reasoning, escalate_immediately)
            or None if the LLM is not configured or fails.
        """
        provider = get_ai_provider()
        if provider is None:
            return None

        ctx = build_context(
            service=buffered_signal.context.service,
            severity=severity,
            region=buffered_signal.context.region,
            environment=buffered_signal.context.environment,
            metric_name=buffered_signal.signal.details.get("metric_name", "unknown")
                        if isinstance(buffered_signal.signal.details, dict)
                        else "unknown",
            observed_value=buffered_signal.signal.metric.value
                           if buffered_signal.signal.metric else 0.0,
            threshold=float(
                buffered_signal.signal.details.get("threshold", 0)
                if isinstance(buffered_signal.signal.details, dict) else 0
            ),
            signal_summary=buffered_signal.signal.summary,
            learn_scores=learn_scores,
        )

        prompt = _build_prompt(ctx)

        try:
            logger.info(
                "Calling LLM for decision: service=%s severity=%s provider=%s model=%s",
                buffered_signal.context.service, severity,
                provider.provider, provider.model,
            )
            raw_text = provider.complete(prompt, system=SYSTEM_PROMPT)
            logger.debug("LLM raw response: %s", raw_text[:500])
        except Exception as exc:
            logger.warning("LLM call failed (%s) — falling back to rule-based", exc)
            return None

        parsed = _parse_response(raw_text)
        if parsed is None:
            logger.warning("LLM response parse failed — falling back to rule-based")
            return None

        steps = _to_decision_steps(parsed, buffered_signal.context.service)
        confidence = float(parsed.get("confidence", 0.5))
        reasoning  = str(parsed.get("reasoning", ""))
        escalate   = bool(parsed.get("escalate_immediately", False))
        escalate_reason = parsed.get("escalate_reason") or ""

        logger.info(
            "LLM decision: service=%s steps=%d confidence=%.2f escalate=%s",
            buffered_signal.context.service, len(steps), confidence, escalate,
        )

        # Log the full reasoning so it appears in server output
        logger.info(
            "LLM reasoning: %s",
            reasoning,
            extra={
                "service": buffered_signal.context.service,
                "severity": severity,
                "confidence": confidence,
                "escalate": escalate,
                "escalate_reason": escalate_reason,
                "actions": [s.action for s in steps],
            },
        )

        # Record each action rationale in the explain audit trail
        try:
            from ..explain import explain_service
            for step in steps:
                explain_service.record_event(
                    component="ai.decide",
                    event_type="decision.llm",
                    message=f"[{step.action}] {step.rationale}",
                    metadata={
                        "reasoning": reasoning,
                        "action": step.action,
                        "confidence": confidence,
                        "escalate_immediately": escalate,
                        "escalate_reason": escalate_reason,
                        "model": provider.model,
                        "provider": provider.provider,
                    },
                )
        except Exception as exc:
            logger.debug("Explain record failed (non-critical): %s", exc)

        return steps, confidence, reasoning, escalate


decision_advisor = DecisionAdvisor()
