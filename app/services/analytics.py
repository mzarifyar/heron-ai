"""Chronicle analytics scaffolding for roadmap+ insights.

"""

from __future__ import annotations

from collections import Counter
from typing import Dict, List

from .chronicle import chronicle_service


class ChronicleAnalyticsService:
    """Provides ChronicleAnalyticsService behavior using local state or integrations and exposes structured outputs for callers."""

    def near_miss_report(self, *, limit: int = 100) -> Dict[str, object]:
        """Builds near miss report using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        incidents = chronicle_service.list_incidents(limit=limit)
        items: List[Dict[str, object]] = []
        for incident in incidents:
            timeline = chronicle_service.list_timeline(incident.incident_id, limit=500)
            near_miss_events = [event for event in timeline if event.near_miss]
            if not near_miss_events:
                continue
            items.append(
                {
                    "incident_id": incident.incident_id,
                    "service": incident.service,
                    "near_miss_count": len(near_miss_events),
                    "latest_event_type": near_miss_events[-1].event_type,
                }
            )
        items.sort(key=lambda item: int(item["near_miss_count"]), reverse=True)
        return {"count": len(items), "items": items}

    def tag_trends(self, *, limit: int = 500) -> Dict[str, object]:
        """Builds tag trends using local reads or integration calls and returns a dictionary payload (e.g., {"count": 1}), may raise ValueError for bad input while dependency errors may bubble."""
        incidents = chronicle_service.list_incidents(limit=limit)
        counts: Counter[str] = Counter()
        for incident in incidents:
            timeline = chronicle_service.list_timeline(incident.incident_id, limit=500)
            for event in timeline:
                counts.update(event.tags)
            counts.update(incident.tags)
        ranked = [
            {"tag": tag, "count": count}
            for tag, count in counts.most_common()
        ]
        return {"count": len(ranked), "items": ranked}


chronicle_analytics_service = ChronicleAnalyticsService()