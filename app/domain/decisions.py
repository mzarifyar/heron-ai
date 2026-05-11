"""Decision and mitigation tracking primitives.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from .actions import ActionPlan


@dataclass
class Decision:
    """Provides Decision behavior using local state or integrations and exposes structured outputs for callers."""
    decision_id: str
    incident_id: str
    rationale: str
    decided_by: str
    decided_at: datetime = field(default_factory=datetime.utcnow)
    actions: List[ActionPlan] = field(default_factory=list)

    def add_action(self, plan: ActionPlan) -> None:
        """Builds add action using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.actions.append(plan)

    def summary(self) -> str:
        """Builds summary using local state or integration calls and returns a string value (e.g., "ok"), may raise ValueError for bad input while dependency errors may bubble."""
        action_text = "; ".join(action.render_summary() for action in self.actions) or "no-op"
        return f"Decision[{self.decision_id}] -> {action_text}"