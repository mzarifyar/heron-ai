"""In-memory anomaly store for Cortex Insight.

"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Deque, List

from ..schemas.anomaly import Anomaly


class AnomalyStore:
    """Provides AnomalyStore behavior using local state or integrations and exposes structured outputs for callers."""

    def __init__(self, capacity: int = 256) -> None:
        """Initializes instance state using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self.capacity = capacity
        self._items: Deque[tuple[datetime, Anomaly]] = deque(maxlen=capacity)

    def add(self, anomaly: Anomaly) -> None:
        """Builds add using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._items.append((anomaly.detected_at, anomaly))

    def list_recent(self, limit: int = 50) -> List[Anomaly]:
        """Lists recent using local reads or integration calls and returns a list result (e.g., []), may raise ValueError for bad input while dependency errors may bubble."""
        return [item for _, item in list(self._items)[-limit:]]

    def clear(self) -> None:
        """Clears the request using local state or integration calls and returns None, may raise ValueError for bad input while dependency errors may bubble."""
        self._items.clear()