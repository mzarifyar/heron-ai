"""Diagnostics-only plan resolver (no action execution).

"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Loads yaml using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    if not path.exists():
        return {}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _merge_catalog(base: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Merges catalog dictionaries using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    out: Dict[str, Any] = dict(base or {})
    defaults = dict(out.get("defaults") or {}) if isinstance(out.get("defaults"), dict) else {}
    plans = dict(out.get("plans") or {}) if isinstance(out.get("plans"), dict) else {}
    fallback = dict(out.get("fallback") or {}) if isinstance(out.get("fallback"), dict) else {}

    incoming_defaults = incoming.get("defaults") if isinstance(incoming.get("defaults"), dict) else {}
    incoming_plans = incoming.get("plans") if isinstance(incoming.get("plans"), dict) else {}
    incoming_fallback = incoming.get("fallback") if isinstance(incoming.get("fallback"), dict) else {}

    defaults.update(incoming_defaults)
    plans.update(incoming_plans)
    fallback.update(incoming_fallback)

    out["defaults"] = defaults
    out["plans"] = plans
    if fallback:
        out["fallback"] = fallback
    return out


def _load_catalog(base_catalog_path: Path) -> Dict[str, Any]:
    """Loads catalog set using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    merged = _load_yaml(base_catalog_path)
    fragments_root = base_catalog_path.parent / "plans"
    if not fragments_root.exists():
        return merged
    for fragment in sorted(fragments_root.rglob("*.yaml")):
        merged = _merge_catalog(merged, _load_yaml(fragment))
    return merged


class DiagnosticsPlanner:
    """Provides DiagnosticsPlanner behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, catalog_path: Path | None = None) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        root = Path(__file__).resolve().parents[2]
        self.catalog_path = catalog_path or (root / "mitigations" / "catalog" / "diagnostics_plans.yaml")
        self._catalog = _load_catalog(self.catalog_path)

    def resolve_preview(self, *, runbook_id: str) -> Dict[str, Any]:
        """Resolves preview using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        rid = (runbook_id or "").strip()
        plans = self._catalog.get("plans") if isinstance(self._catalog.get("plans"), dict) else {}
        defaults = self._catalog.get("defaults") if isinstance(self._catalog.get("defaults"), dict) else {}
        fallback = self._catalog.get("fallback") if isinstance(self._catalog.get("fallback"), dict) else {}
        selected = plans.get(rid) if rid and isinstance(plans, dict) else None
        source = "plan" if isinstance(selected, dict) else "fallback"
        payload = selected if isinstance(selected, dict) else fallback

        steps_raw = payload.get("steps") if isinstance(payload, dict) else []
        steps = steps_raw if isinstance(steps_raw, list) else []
        steps_list: List[str] = [str(item).strip() for item in steps if str(item).strip()]
        plan_max_steps = payload.get("max_steps") if isinstance(payload, dict) else None
        max_steps = int(plan_max_steps or defaults.get("max_steps", 8))
        steps_list = steps_list[: max(1, max_steps)]

        return {
            "runbook_id": rid or None,
            "source": source,
            "title": str(payload.get("title") or "Generic Alert Diagnostics"),
            "intent": str(payload.get("intent") or "Collect baseline diagnostics."),
            "severity": str(payload.get("severity") or "s4"),
            "steps": steps_list,
            "steps_count": len(steps_list),
            "execution_mode": "preview_only",
        }


diagnostics_planner = DiagnosticsPlanner()
