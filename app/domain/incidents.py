"""Domain helpers for Cortex incidents and timelines.

"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class IncidentNote:
    """Provides IncidentNote behavior using local state or integrations and exposes structured outputs for callers."""
    author: str
    body: str
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Incident:
    """Provides Incident behavior using local state or integrations and exposes structured outputs for callers."""
    incident_id: str
    title: str
    severity: str
    service: str
    status: str = "open"
    detected_at: datetime = field(default_factory=datetime.utcnow)
    notes: List[IncidentNote] = field(default_factory=list)

    def add_note(self, author: str, body: str) -> IncidentNote:
        """Builds add note using local state or integration calls and returns a result value, may raise ValueError for bad input while dependency errors may bubble."""
        note = IncidentNote(author=author, body=body)
        self.notes.append(note)
        return note

    def close(self, resolution: Optional[str] = None) -> None:
        """Builds close using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.status = "closed"
        if resolution:
            self.add_note(author="system", body=f"Resolution: {resolution}")