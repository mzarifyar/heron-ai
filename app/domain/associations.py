"""Association helpers imported from the legacy Cortex processor.

Maps normalized alarm messages to configured groups/actions/components based on
``config/dvm.json`` (or the legacy ``config/associations.json`` fallback).

"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Set
import json
import os

from utils.logger import log
from utils.settings import get_sys_path

from .parsers import normalize_message

__all__ = ["load_association_config"]


def _default_config_path() -> Path:
    """Builds default config path using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    base = Path(get_sys_path() or ".") / "config"
    primary = base / "dvm.json"
    legacy = base / "associations.json"
    if primary.exists():
        return primary
    if legacy.exists():
        return legacy
    return primary


def load_association_config(path: str | os.PathLike[str] | None = None) -> Dict[str, Any]:
    """Loads association config using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
    config_path = Path(path) if path else _default_config_path()
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        log("error", "Failed to load association config from {}: {}", str(config_path), exc)
        return {"msg_to_group": {}, "group_to_msgs": {}, "group_actions": {}, "group_components": {}}

    msg_to_group: Dict[str, str] = {}
    group_to_msgs: Dict[str, Set[str]] = {}
    group_actions: Dict[str, str] = {}
    group_components: Dict[str, str] = {}

    for group in data.get("alarm_groups", []):
        name = group.get("name")
        if not name:
            continue
        titles = group.get("alarm_titles", [])
        normalized = {normalize_message(title) for title in titles if title}
        group_to_msgs[name] = normalized
        for message in normalized:
            msg_to_group[message] = name

        action = group.get("action")
        if isinstance(action, str):
            group_actions[name] = action

        component_name = group.get("component_name") or group.get("component")
        if isinstance(component_name, str):
            group_components[name] = component_name

    return {
        "msg_to_group": msg_to_group,
        "group_to_msgs": group_to_msgs,
        "group_actions": group_actions,
        "group_components": group_components,
    }