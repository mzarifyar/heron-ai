"""What-if simulation scaffolding for Chronicle roadmap+.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import uuid
from typing import Dict, List

from ..core import get_logger
from .chronicle import chronicle_service

logger = get_logger(__name__)


@dataclass
class SimulationResult:
    """Provides SimulationResult behavior using local state or integrations and exposes structured outputs for callers."""
    simulation_id: str
    incident_id: str
    created_at: datetime
    assumptions: Dict[str, object] = field(default_factory=dict)
    proposed_actions: List[str] = field(default_factory=list)
    estimated_outcome: str = "unknown"
    notes: str = ""


class WhatIfSimulationService:
    """Provides WhatIfSimulationService behavior using local state or integrations and exposes structured outputs for callers."""

    def simulate_incident(
        self,
        incident_id: str,
        *,
        assumptions: Dict[str, object] | None = None,
        alternate_actions: List[str] | None = None,
    ) -> SimulationResult:
        """Builds simulate incident using local reads or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        incident = chronicle_service.get_incident(incident_id)
        if incident is None:
            raise KeyError(f"incident {incident_id} not found")

        timeline = chronicle_service.list_timeline(incident_id, limit=500)
        actionable_events = [item for item in timeline if item.event_type.startswith("actions.")]
        if alternate_actions:
            proposed_actions = list(alternate_actions)
        else:
            proposed_actions = [
                str(item.metadata.get("action", item.event_type))
                for item in actionable_events[-3:]
            ]

        estimated_outcome = "likely_improvement" if proposed_actions else "insufficient_data"
        result = SimulationResult(
            simulation_id=f"sim-{uuid.uuid4().hex[:10]}",
            incident_id=incident_id,
            created_at=datetime.utcnow(),
            assumptions=assumptions or {},
            proposed_actions=proposed_actions,
            estimated_outcome=estimated_outcome,
            notes="Scaffold result. Future revisions should replay historical metrics and policy variants.",
        )
        logger.info(
            "What-if simulation generated",
            extra={"simulation_id": result.simulation_id, "incident_id": incident_id},
        )
        return result


what_if_simulation_service = WhatIfSimulationService()