"""Common mitigation and action models used throughout Heron.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional


@dataclass
class ActionPlan:
    """Provides ActionPlan behavior using local state or integrations and exposes structured outputs for callers."""
    action_id: str
    title: str
    runbook_id: Optional[str] = None
    parameters: Dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)

    def render_summary(self) -> str:
        """Renders summary using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        param_blob = ", ".join(f"{k}={v}" for k, v in sorted(self.parameters.items()))
        return f"{self.title} (runbook={self.runbook_id or 'n/a'}; {param_blob})"