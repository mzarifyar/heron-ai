"""
Utilities for exporting passive-mode run artifacts for evaluation.

The exporter is intentionally side-effect free unless explicitly enabled via
environment variables. When ``HERON_PASSIVE_EXPORT_DIR`` is set, the recorder
captures the processor summary and emits a deterministic JSON artifact that the
evaluation harness can consume later.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ISO_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def _iso_now() -> str:
    """Builds iso now using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    return datetime.now(timezone.utc).strftime(ISO_FORMAT)


def _clean_identifier(value: str) -> str:
    """Builds clean identifier using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    return value.replace(" ", "_").lower()


def _stable_sorted(items: List[Dict[str, Any]], key: str) -> List[Dict[str, Any]]:
    """Builds stable sorted using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return sorted(items, key=lambda item: item.get(key) or "")


def _normalize_group_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Normalizes group entry using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    group = entry.get("group") or "unknown_group"
    keys = sorted(entry.get("keys") or [])
    identifier = f"{_clean_identifier(group)}::{';'.join(keys)}" if keys else _clean_identifier(group)
    return {
        "identifier": identifier,
        "type": "group_action",
        "group": group,
        "command": entry.get("action") or "",
        "keys": keys,
        "context": entry.get("context"),
        "success": bool(entry.get("action_result", {}).get("success", True)),
        "followup_ticket": entry.get("followup_ticket"),
    }


def _normalize_followup(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalizes followup using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    followup = entry.get("followup_ticket") or {}
    if not isinstance(followup, dict):
        return None
    key = followup.get("key")
    if not key:
        return None
    return {
        "identifier": key,
        "type": "followup_incident",
        "severity": followup.get("fields", {}).get("priority"),
        "metadata": {
            "group": entry.get("group"),
            "context": entry.get("context"),
            "action": entry.get("action"),
        },
    }


def _normalize_ai_ticket(identifier: str) -> Dict[str, Any]:
    """Normalizes ai ticket using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    return {
        "identifier": identifier,
        "type": "ai_escalation",
        "severity": "sev4",
        "metadata": {},
    }


def _normalize_summary(
    summary: Dict[str, Any],
    scenario_id: str,
    run_id: str,
    run_metadata: Dict[str, Any],
) -> Dict[str, Any]:
    """Normalizes summary using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    groups = summary.get("groups_formed") or []
    normalized_groups = [_normalize_group_entry(g) for g in groups if isinstance(g, dict)]
    planned_actions = _stable_sorted(normalized_groups, "identifier")

    escalations: List[Dict[str, Any]] = []
    for g in normalized_groups:
        followup = _normalize_followup(g)
        if followup:
            escalations.append(followup)

    for ticket in summary.get("ai_high_severity_created") or []:
        if isinstance(ticket, str) and ticket.strip():
            escalations.append(_normalize_ai_ticket(ticket.strip()))

    observed_escalations = _stable_sorted(escalations, "identifier")

    evidence_refs: List[Dict[str, Any]] = []
    for g in normalized_groups:
        evidence_refs.append(
            {
                "type": "action_result",
                "identifier": g["identifier"],
                "success": g.get("success"),
            }
        )

    return {
        "run_id": run_id,
        "generated_at": _iso_now(),
        "scenarios": [
            {
                "scenario_id": scenario_id,
                "observed_escalations": observed_escalations,
                "observed_planned_actions": planned_actions,
                "observed_non_escalations": [],
                "evidence_refs": evidence_refs,
                "timestamps": {
                    "last_run_updated_to": summary.get("last_run_updated_to"),
                },
            }
        ],
        "metadata": run_metadata,
        "summary_source": "processor",
    }


@dataclass
class PassiveRunRecorder:
    """Provides PassiveRunRecorder behavior using local state or integrations and exposes structured outputs for callers."""
    enabled: bool = field(init=False)
    export_dir: Optional[Path] = field(init=False, default=None)
    run_id: str = field(init=False, default="")
    scenario_id: str = field(init=False, default="default")

    def __post_init__(self) -> None:
        """Handles post init protocol behavior using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        root = os.getenv("HERON_PASSIVE_EXPORT_DIR")
        if not root:
            self.enabled = False
            return

        export_path = Path(root).expanduser()
        export_path.mkdir(parents=True, exist_ok=True)

        run_id = os.getenv("HERON_PASSIVE_RUN_ID") or uuid.uuid4().hex
        scenario_id = os.getenv("HERON_SCENARIO_ID") or "default"

        self.enabled = True
        self.export_dir = export_path
        self.run_id = run_id
        self.scenario_id = scenario_id

    def record_processor_summary(self, summary: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> None:
        """Records processor summary using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        if not self.enabled or self.export_dir is None:
            return

        payload = _normalize_summary(summary, self.scenario_id, self.run_id, metadata or {})

        destination = self.export_dir / "observed.normalized.json"
        with destination.open("w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2, sort_keys=True)


_RECORDER = PassiveRunRecorder()


def record_passive_run_summary(summary: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> None:
    """Records passive run summary using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""

    if not isinstance(summary, dict):
        return
    _RECORDER.record_processor_summary(summary, metadata)

