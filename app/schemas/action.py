"""Action execution schemas for Heron Reflex.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class ActionAttempt:
    """Provides ActionAttempt behavior using local state or integrations and exposes structured outputs for callers."""

    command: str
    started_at: datetime
    executor: str = "command"
    finished_at: Optional[datetime] = None
    success: bool = False
    details: Optional[str] = None
    output: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionExecution:
    """Provides ActionExecution behavior using local state or integrations and exposes structured outputs for callers."""

    action_id: str
    action_name: str = "unknown"
    decision_id: Optional[str] = None
    status: str = "pending"
    dry_run: bool = False
    cooldown_seconds: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    attempts: List[ActionAttempt] = field(default_factory=list)
    started_at: datetime = field(default_factory=datetime.utcnow)
    finished_at: Optional[datetime] = None


def create_execution(
    action_id: str,
    command: str,
    *,
    action_name: str = "unknown",
    decision_id: Optional[str] = None,
    dry_run: bool = False,
    executor: str = "command",
    metadata: Optional[Dict[str, Any]] = None,
) -> ActionExecution:
    """Creates execution using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
    attempt = ActionAttempt(command=command, executor=executor, started_at=datetime.utcnow())
    return ActionExecution(
        action_id=action_id,
        action_name=action_name,
        decision_id=decision_id,
        dry_run=dry_run,
        metadata=metadata or {},
        attempts=[attempt],
    )