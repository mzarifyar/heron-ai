"""Persistent ticket + association state lifted from the legacy Heron processor.

The original project kept runtime artifacts under ``data/`` (outside git).
We mirror that behavior so ingestion services in Heron can reuse the
established guardrails (ticket store, dvms dedupe map, hourly limits).

"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple
import json
import os

from utils.logger import log
from utils.settings import get_sys_path

SYS_PATH = get_sys_path() or "."
DATA_DIR = Path(SYS_PATH) / "data"
DVMS_PATH = DATA_DIR / "dvms_found.json"
TICKET_STORE_PATH = DATA_DIR / "tickets_store.json"

__all__ = [
    "ensure_data_files",
    "read_ticket_store",
    "write_ticket_store",
    "upsert_ticket",
    "register_group_occurrence",
    "mark_ticket_resolved_in_dvms",
]


def _ensure_dir(path: Path) -> None:
    """Ensures dir using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    path.parent.mkdir(parents=True, exist_ok=True)


def ensure_data_files() -> None:
    """Ensures data files using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if not DVMS_PATH.exists():
        log("info", "Creating dvms_found.json at {}", str(DVMS_PATH))
        _ensure_dir(DVMS_PATH)
        DVMS_PATH.write_text(json.dumps({"groups": {}, "message_group_events": {}}, indent=2), encoding="utf-8")

    if not TICKET_STORE_PATH.exists():
        log("info", "Creating tickets_store.json at {}", str(TICKET_STORE_PATH))
        write_ticket_store([])


def read_ticket_store(path: Path = TICKET_STORE_PATH) -> List[Dict[str, Any]]:
    """Reads ticket store using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - defensive
        log("error", "Failed to read ticket store from {}: {}", str(path), exc)
        return []


def write_ticket_store(items: List[Dict[str, Any]], path: Path = TICKET_STORE_PATH) -> None:
    """Writes ticket store using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    _ensure_dir(path)
    path.write_text(json.dumps(items, indent=2), encoding="utf-8")


def upsert_ticket(store: List[Dict[str, Any]], entry: Dict[str, Any]) -> None:
    """Upserts ticket using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    key = entry.get("key")
    current_time = datetime.now(timezone.utc).isoformat()
    entry["added_at"] = current_time
    for idx, existing in enumerate(store):
        if existing.get("key") == key:
            entry["added_at"] = existing.get("added_at", current_time)
            store[idx] = entry
            return
    store.append(entry)


def _load_dvms_data(file_path: Path) -> Dict[str, Any]:
    """Loads dvms data using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    if not file_path.exists():
        return {"groups": {}, "message_group_events": {}}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        log("info", "dvms_found.json malformed; resetting to empty structure")
        return {"groups": {}, "message_group_events": {}}
    if not isinstance(data, dict):
        return {"groups": {}, "message_group_events": {}}
    data.setdefault("groups", {})
    data.setdefault("message_group_events", {})
    return data


def _persist_dvms_data(file_path: Path, data: Dict[str, Any]) -> None:
    """Builds persist dvms data using local writes or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    _ensure_dir(file_path)
    file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _prune_events(events: List[str], window_start: datetime) -> Tuple[List[str], int]:
    """Prunes events using local state or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
    kept: List[str] = []
    for ts in events:
        try:
            dt = datetime.fromisoformat(ts)
        except ValueError:
            continue
        if dt >= window_start:
            kept.append(ts)
    return kept, len(kept)


def register_group_occurrence(
    file_path: Path,
    message_group: str,
    tickets: List[Dict[str, str]],
    hourly_limit: int,
) -> Dict[str, Any]:
    """Builds register group occurrence using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    _ensure_dir(file_path)
    dedup_keys = sorted({(t.get("key") or "").strip() for t in tickets if t.get("key")})
    if not dedup_keys:
        return {
            "should_process": False,
            "reason": "no_keys",
            "recent_count": 0,
            "limit": hourly_limit,
            "keyset_token": "",
        }

    payload = _load_dvms_data(file_path)
    groups = payload["groups"]
    message_group_events = payload["message_group_events"]

    keyset_token = "|".join(dedup_keys)
    group_entry = groups.setdefault(
        keyset_token,
        {
            "keys": dedup_keys,
            "pairs": [{"key": t.get("key"), "summary": t.get("summary")} for t in tickets],
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
        },
    )

    if group_entry["keys"] != dedup_keys:
        group_entry["keys"] = dedup_keys
    group_entry["last_seen"] = datetime.now(timezone.utc).isoformat()

    window_start = datetime.now(timezone.utc) - timedelta(hours=1)
    events = message_group_events.setdefault(message_group, [])
    events, _ = _prune_events(events, window_start)
    message_group_events[message_group] = events

    should_process = True
    reason = "allowed"
    if hourly_limit and len(events) >= hourly_limit:
        should_process = False
        reason = "rate_limited"
    elif keyset_token in groups and groups[keyset_token] is not group_entry:
        should_process = False
        reason = "duplicate_keyset"

    if should_process:
        events.append(datetime.now(timezone.utc).isoformat())

    _persist_dvms_data(file_path, payload)
    return {
        "should_process": should_process,
        "reason": reason,
        "recent_count": len(events),
        "limit": hourly_limit,
        "keyset_token": keyset_token,
    }


def mark_ticket_resolved_in_dvms(ticket_key: str) -> None:
    """Builds mark ticket resolved in dvms using local reads or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
    payload = _load_dvms_data(DVMS_PATH)
    changed = False
    for group in payload["groups"].values():
        for pair in group.get("pairs", []):
            if pair.get("key") == ticket_key:
                pair["resolved_at"] = datetime.now(timezone.utc).isoformat()
                changed = True
    if changed:
        _persist_dvms_data(DVMS_PATH, payload)