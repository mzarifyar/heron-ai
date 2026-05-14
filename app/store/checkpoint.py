"""Checkpoint utilities mirrored from the legacy Heron processor.

These helpers persist the last successful Jira poll timestamp under
``<SYS_PATH>/data/checkpoint.json`` so repeated ingestion runs only fetch
newer tickets. The JSON structure matches the original implementation:

{
  "last_run_utc": "2026-01-30T11:22:00Z"
}

"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional
import json
import os

from utils.settings import get_sys_path

DATA_DIR = Path(get_sys_path() or ".") / "data"
CHECKPOINT_PATH = DATA_DIR / "checkpoint.json"

__all__ = [
    "ensure_checkpoint_dir",
    "read_last_run_iso",
    "read_last_run_jql_timestamp",
    "write_checkpoint_iso",
    "write_checkpoint_now",
]


def ensure_checkpoint_dir() -> None:
    """Ensures checkpoint dir using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)


def read_last_run_iso(path: Path = CHECKPOINT_PATH) -> Optional[str]:
    """Reads last run iso using local reads or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    if not path.exists():
        return None
    try:
        data: Dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    val = data.get("last_run_utc")
    return val if isinstance(val, str) and val else None


def _iso_to_jql(ts_iso: str) -> Optional[str]:
    """Builds iso to jql using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        ts = ts_iso
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None


def read_last_run_jql_timestamp(path: Path = CHECKPOINT_PATH) -> Optional[str]:
    """Reads last run jql timestamp using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    iso = read_last_run_iso(path)
    if not iso:
        return None
    return _iso_to_jql(iso)


def write_checkpoint_iso(ts_iso: str, path: Path = CHECKPOINT_PATH) -> None:
    """Writes checkpoint iso using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    ensure_checkpoint_dir()
    payload = {"last_run_utc": ts_iso}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_checkpoint_now(path: Path = CHECKPOINT_PATH) -> str:
    """Writes checkpoint now using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    write_checkpoint_iso(now_iso, path)
    return now_iso