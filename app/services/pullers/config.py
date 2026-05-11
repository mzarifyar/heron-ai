"""Configuration loader for external data pullers.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

import yaml


@dataclass
class PullerSourceConfig:
    """Provides PullerSourceConfig behavior using local state or integrations and exposes structured outputs for callers."""
    name: str
    enabled: bool = False
    interval_seconds: int = 300
    range_hours: int = 24
    batch_size: int = 200
    jitter_seconds: int = 0


@dataclass
class PullersConfig:
    """Provides PullersConfig behavior using local state or integrations and exposes structured outputs for callers."""
    scheduler_enabled: bool = False
    sources: Dict[str, PullerSourceConfig] = field(default_factory=dict)


DEFAULT_CONFIG = PullersConfig(
    scheduler_enabled=False,
    sources={
        "jira": PullerSourceConfig(
            name="jira",
            enabled=True,
            interval_seconds=300,
            range_hours=24,
            batch_size=200,
            jitter_seconds=5,
        ),
        "devops_portal": PullerSourceConfig(
            name="devops_portal",
            enabled=False,
            interval_seconds=60,
            range_hours=24,
            batch_size=200,
            jitter_seconds=5,
        ),
        "cluster_hygiene": PullerSourceConfig(
            name="cluster_hygiene",
            enabled=False,
            interval_seconds=300,
            range_hours=24,
            batch_size=200,
            jitter_seconds=5,
        ),
    },
)


def _coerce_int(value: Any, default: int, minimum: int = 1) -> int:
    """Builds coerce int using local state or integration calls and returns an integer value (e.g., 1), may raise ValueError for bad input while dependency errors may bubble."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return parsed if parsed >= minimum else default


def load_pullers_config(path: str) -> PullersConfig:
    """Loads pullers config using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    merged = PullersConfig(
        scheduler_enabled=DEFAULT_CONFIG.scheduler_enabled,
        sources={
            name: PullerSourceConfig(**vars(source))
            for name, source in DEFAULT_CONFIG.sources.items()
        },
    )

    config_path = Path(path)
    if not config_path.exists():
        return merged

    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return merged

    if not isinstance(payload, dict):
        return merged

    scheduler = payload.get("scheduler")
    if isinstance(scheduler, dict):
        merged.scheduler_enabled = bool(scheduler.get("enabled", merged.scheduler_enabled))

    sources = payload.get("sources")
    if not isinstance(sources, dict):
        return merged

    for name, source_payload in sources.items():
        if not isinstance(name, str) or not isinstance(source_payload, dict):
            continue
        base = merged.sources.get(name, PullerSourceConfig(name=name))
        merged.sources[name] = PullerSourceConfig(
            name=name,
            enabled=bool(source_payload.get("enabled", base.enabled)),
            interval_seconds=_coerce_int(source_payload.get("interval_seconds"), base.interval_seconds),
            range_hours=_coerce_int(source_payload.get("range_hours"), base.range_hours),
            batch_size=_coerce_int(source_payload.get("batch_size"), base.batch_size),
            jitter_seconds=_coerce_int(source_payload.get("jitter_seconds"), base.jitter_seconds, minimum=0),
        )
    return merged