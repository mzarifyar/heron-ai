"""Jira puller adapter for the puller scheduler.

"""

from __future__ import annotations

from typing import Any, Dict

from app.services.jira_processor import jira_processor


class JiraPuller:
    """Provides JiraPuller behavior using local state or integrations and exposes structured outputs for callers."""

    def run(self, *, range_hours: int) -> Dict[str, Any]:
        """Runs the request using local state or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        return jira_processor.process_tickets(range_hours=range_hours)