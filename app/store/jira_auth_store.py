"""Local persisted Jira auth token helpers.

"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict
import json

from ..core import get_settings


class JiraAuthStore:
    """Provides JiraAuthStore behavior using local state or integrations and exposes structured outputs for callers."""
    def __init__(self) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._lock = Lock()

    def _path(self) -> Path:
        """Builds path using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        return Path(get_settings().jira_auth_store_path)

    def load(self) -> Dict[str, Any]:
        """Loads the request using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        path = self._path()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def get_token(self) -> str | None:
        """Gets token using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        payload = self.load()
        token = payload.get("token")
        if isinstance(token, str) and token.strip():
            return token.strip()
        return None

    def save_token(self, token: str, *, source: str = "ui") -> Dict[str, Any]:
        """Saves token using local writes or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        cleaned = token.strip()
        if not cleaned:
            raise ValueError("token is required")
        now = datetime.now(timezone.utc).isoformat()
        payload = {"token": cleaned, "source": source, "updated_at": now}
        path = self._path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return {"source": source, "updated_at": now}

    def clear(self) -> None:
        """Clears the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        path = self._path()
        with self._lock:
            if path.exists():
                path.unlink()

    def status(self) -> Dict[str, Any]:
        """Builds status using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        payload = self.load()
        token = payload.get("token")
        masked = None
        if isinstance(token, str) and len(token) >= 8:
            masked = f"{token[:4]}...{token[-4:]}"
        elif isinstance(token, str) and token:
            masked = "****"
        return {
            "has_token": bool(token),
            "source": payload.get("source"),
            "updated_at": payload.get("updated_at"),
            "token_preview": masked,
            "store_path": str(self._path()),
        }


jira_auth_store = JiraAuthStore()