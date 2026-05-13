"""Discovery adapter interface and shared data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ResourceItem:
    """One discovered cloud resource."""
    id: str                          # cloud-native resource OCID / ARN / etc.
    name: str
    resource_type: str               # compute | database | kubernetes | lb | network | storage
    region: str
    compartment: str                 # compartment (OCI) / account (AWS) / project (GCP)
    status: str = "unknown"          # monitored | partial | unmonitored | unknown
    monitoring_sources: list[str] = field(default_factory=list)
    alarm_count: int = 0
    metric_namespaces: list[str] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name,
            "resource_type": self.resource_type, "region": self.region,
            "compartment": self.compartment, "status": self.status,
            "monitoring_sources": self.monitoring_sources,
            "alarm_count": self.alarm_count,
            "metric_namespaces": self.metric_namespaces,
            "tags": self.tags,
        }


@dataclass
class ScanResult:
    """Result of a full cloud discovery scan."""
    cloud: str
    resources: list[ResourceItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scan_duration_seconds: float = 0.0
    scanned_at: datetime = field(default_factory=datetime.utcnow)

    @property
    def monitored(self) -> list[ResourceItem]:
        return [r for r in self.resources if r.status == "monitored"]

    @property
    def partial(self) -> list[ResourceItem]:
        return [r for r in self.resources if r.status == "partial"]

    @property
    def unmonitored(self) -> list[ResourceItem]:
        return [r for r in self.resources if r.status == "unmonitored"]

    @property
    def unknown(self) -> list[ResourceItem]:
        return [r for r in self.resources if r.status == "unknown"]

    def summary(self) -> dict[str, Any]:
        by_type: dict[str, int] = {}
        for r in self.resources:
            by_type[r.resource_type] = by_type.get(r.resource_type, 0) + 1
        return {
            "cloud": self.cloud,
            "total": len(self.resources),
            "monitored": len(self.monitored),
            "partial": len(self.partial),
            "unmonitored": len(self.unmonitored),
            "unknown": len(self.unknown),
            "by_type": by_type,
            "errors": len(self.errors),
            "scanned_at": self.scanned_at.isoformat(),
            "scan_duration_seconds": round(self.scan_duration_seconds, 2),
        }
