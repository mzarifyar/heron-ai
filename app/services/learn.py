"""Cortex Learn: advisory action effectiveness tracking.

"""

from __future__ import annotations
from app.core.paths import data as _dat

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Tuple
import json

from ..core import get_logger

logger = get_logger(__name__)


@dataclass
class ActionStats:
    """Provides ActionStats behavior using local state or integrations and exposes structured outputs for callers."""
    total: int = 0
    success: int = 0

    @property
    def success_rate(self) -> float:
        """Builds success rate using local state or integration calls and returns a numeric value (e.g., 1.0), may raise ValueError for bad input while dependency errors may bubble."""
        if self.total <= 0:
            return 0.0
        return self.success / self.total

    def to_dict(self) -> Dict[str, Any]:
        """Builds to dict using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        return {
            "total": self.total,
            "success": self.success,
            "success_rate": round(self.success_rate, 4),
        }


class LearnService:
    """Provides LearnService behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, *, state_path: str = _dat("learn_state.json"), min_samples: int = 3) -> None:
        """Initializes instance state using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._state_path = Path(state_path)
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._min_samples = min_samples
        self._lock = Lock()
        self._global: Dict[str, ActionStats] = {}
        self._scoped: Dict[Tuple[str, str, str], ActionStats] = {}
        self._last_updated_at: str | None = None
        self._load()

    @staticmethod
    def _scope_key(service: str, severity: str, action: str) -> Tuple[str, str, str]:
        """Builds scope key using local state or integration calls and returns a tuple result (e.g., ()), may raise ValueError for bad input while dependency errors may bubble."""
        return (service.strip().lower(), severity.strip().lower(), action.strip())

    def _load(self) -> None:
        """Loads the request using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        if not self._state_path.exists():
            return
        try:
            payload = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to load learn state: %s", exc)
            return
        if not isinstance(payload, dict):
            return
        global_raw = payload.get("global")
        scoped_raw = payload.get("scoped")
        self._last_updated_at = payload.get("updated_at")
        if isinstance(global_raw, dict):
            for action, item in global_raw.items():
                if isinstance(action, str) and isinstance(item, dict):
                    self._global[action] = ActionStats(
                        total=int(item.get("total", 0)),
                        success=int(item.get("success", 0)),
                    )
        if isinstance(scoped_raw, dict):
            for key, item in scoped_raw.items():
                if not isinstance(key, str) or not isinstance(item, dict):
                    continue
                parts = key.split("|")
                if len(parts) != 3:
                    continue
                self._scoped[(parts[0], parts[1], parts[2])] = ActionStats(
                    total=int(item.get("total", 0)),
                    success=int(item.get("success", 0)),
                )

    def _persist(self) -> None:
        """Builds persist using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        payload = {
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
            "global": {action: stats.to_dict() for action, stats in self._global.items()},
            "scoped": {"|".join(key): stats.to_dict() for key, stats in self._scoped.items()},
            "min_samples": self._min_samples,
        }
        self._state_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._last_updated_at = payload["updated_at"]

    def observe_action_outcome(self, *, service: str, severity: str, action: str, success: bool) -> None:
        """Builds observe action outcome using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        key = self._scope_key(service, severity, action)
        with self._lock:
            global_stats = self._global.setdefault(action, ActionStats())
            scoped_stats = self._scoped.setdefault(key, ActionStats())
            global_stats.total += 1
            scoped_stats.total += 1
            if success:
                global_stats.success += 1
                scoped_stats.success += 1
            self._persist()

    def rank_actions(self, *, service: str, severity: str, actions: List[str]) -> List[str]:
        """Builds rank actions using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        if len(actions) <= 1:
            return actions
        scoped_service = service.strip().lower()
        scoped_severity = severity.strip().lower()

        def score(action: str) -> Tuple[int, float, float]:
            """Builds score using local reads or integration calls and returns a tuple result (e.g., ()), may raise ValueError for bad input while dependency errors may bubble."""
            scoped = self._scoped.get((scoped_service, scoped_severity, action))
            global_stats = self._global.get(action)
            scoped_total = scoped.total if scoped else 0
            global_total = global_stats.total if global_stats else 0
            if scoped and scoped_total >= self._min_samples:
                return (2, scoped.success_rate, scoped_total)
            if global_stats and global_total >= self._min_samples:
                return (1, global_stats.success_rate, global_total)
            return (0, 0.0, 0.0)

        ranked = sorted(actions, key=lambda action: score(action), reverse=True)
        return ranked

    def recommendations(self, *, service: str | None = None, severity: str | None = None) -> Dict[str, Any]:
        """Builds recommendations using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        with self._lock:
            scoped_items = []
            for (svc, sev, action), stats in self._scoped.items():
                if service and svc != service.strip().lower():
                    continue
                if severity and sev != severity.strip().lower():
                    continue
                scoped_items.append(
                    {
                        "service": svc,
                        "severity": sev,
                        "action": action,
                        **stats.to_dict(),
                    }
                )
            scoped_items.sort(key=lambda item: (item["success_rate"], item["total"]), reverse=True)
            global_items = [
                {"action": action, **stats.to_dict()}
                for action, stats in self._global.items()
            ]
            global_items.sort(key=lambda item: (item["success_rate"], item["total"]), reverse=True)
            return {
                "updated_at": self._last_updated_at,
                "min_samples": self._min_samples,
                "global": global_items,
                "scoped": scoped_items,
            }

    def summary(self) -> Dict[str, Any]:
        """Builds summary using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        with self._lock:
            return {
                "updated_at": self._last_updated_at,
                "actions_tracked": len(self._global),
                "scopes_tracked": len(self._scoped),
                "min_samples": self._min_samples,
            }

    def clear(self) -> None:
        """Clears the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        with self._lock:
            self._global.clear()
            self._scoped.clear()
            self._last_updated_at = None
            if self._state_path.exists():
                self._state_path.unlink()


learn_service = LearnService()