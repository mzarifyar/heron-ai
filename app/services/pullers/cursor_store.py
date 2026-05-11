"""Persistence helpers for puller cursors and run metadata.

"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict
import json


class PullerCursorStore:
    """Provides PullerCursorStore behavior using local state or integrations and exposes structured outputs for callers."""
    def __init__(self, path: str) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.path = Path(path)
        self._lock = Lock()

    def _read_unlocked(self) -> Dict[str, Any]:
        """Reads unlocked using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        if not self.path.exists():
            return {"sources": {}, "updated_at": None}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {"sources": {}, "updated_at": None}
        if not isinstance(payload, dict):
            return {"sources": {}, "updated_at": None}
        sources = payload.get("sources")
        if not isinstance(sources, dict):
            sources = {}
        return {"sources": sources, "updated_at": payload.get("updated_at")}

    def read_all(self) -> Dict[str, Any]:
        """Reads all using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        with self._lock:
            return self._read_unlocked()

    def upsert_source(self, source: str, cursor: Dict[str, Any]) -> None:
        """Upserts source using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        with self._lock:
            payload = self._read_unlocked()
            payload["sources"][source] = cursor
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")