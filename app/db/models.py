"""SQLAlchemy ORM models for Cortex persistent storage."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index,
    Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from .base import Base


# ── Incidents ──────────────────────────────────────────────────────────────

class Incident(Base):
    __tablename__ = "incidents"

    id:              Mapped[str]           = mapped_column(String(36), primary_key=True)
    title:           Mapped[str]           = mapped_column(String(500))
    severity:        Mapped[str]           = mapped_column(String(10), index=True)   # sev1-sev4
    status:          Mapped[str]           = mapped_column(String(20), index=True)   # active/resolved/escalated
    service:         Mapped[str]           = mapped_column(String(100), index=True)
    region:          Mapped[str]           = mapped_column(String(50))
    environment:     Mapped[str]           = mapped_column(String(20))
    org_id:          Mapped[str]           = mapped_column(String(100), default="default", index=True)
    started_at:      Mapped[datetime]      = mapped_column(DateTime, index=True)
    resolved_at:     Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    duration_seconds:Mapped[int|None]      = mapped_column(Integer, nullable=True)
    auto_healed:     Mapped[bool]          = mapped_column(Boolean, default=False)
    mttr_seconds:    Mapped[int|None]      = mapped_column(Integer, nullable=True)
    created_at:      Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:      Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    timeline:    Mapped[list["TimelineEvent"]] = relationship("TimelineEvent", back_populates="incident", cascade="all, delete-orphan")
    annotations: Mapped[list["Annotation"]]   = relationship("Annotation", back_populates="incident", cascade="all, delete-orphan")
    postmortem:  Mapped["Postmortem | None"]  = relationship("Postmortem", back_populates="incident", uselist=False, cascade="all, delete-orphan")
    actions:     Mapped[list["Action"]]       = relationship("Action", back_populates="incident", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_incidents_started_status", "started_at", "status"),
        Index("ix_incidents_org_service", "org_id", "service"),
    )


class TimelineEvent(Base):
    __tablename__ = "incident_timeline"

    id:          Mapped[str]      = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str]      = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    event_type:  Mapped[str]      = mapped_column(String(80))
    description: Mapped[str]      = mapped_column(Text)
    actor:       Mapped[str]      = mapped_column(String(50), default="cortex")   # cortex / human
    severity:    Mapped[str]      = mapped_column(String(20), default="info")
    timestamp:   Mapped[datetime] = mapped_column(DateTime, index=True)
    metadata_:   Mapped[Any]      = mapped_column("metadata", JSON, nullable=True)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="timeline")


class Annotation(Base):
    __tablename__ = "incident_annotations"

    id:          Mapped[str]      = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str]      = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), index=True)
    author:      Mapped[str]      = mapped_column(String(120))
    content:     Mapped[str]      = mapped_column(Text)
    created_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="annotations")


class Postmortem(Base):
    __tablename__ = "postmortems"

    id:          Mapped[str]      = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str]      = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), unique=True)
    content:     Mapped[str]      = mapped_column(Text)   # full markdown
    author:      Mapped[str]      = mapped_column(String(120))
    created_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at:  Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    incident: Mapped["Incident"] = relationship("Incident", back_populates="postmortem")


# ── Signals ────────────────────────────────────────────────────────────────

class Signal(Base):
    __tablename__ = "signals"

    id:          Mapped[str]      = mapped_column(String(36), primary_key=True)
    source:      Mapped[str]      = mapped_column(String(50))
    metric_name: Mapped[str]      = mapped_column(String(100), index=True)
    value:       Mapped[float]    = mapped_column(Float)
    severity:    Mapped[str]      = mapped_column(String(20))
    service:     Mapped[str]      = mapped_column(String(100), index=True)
    region:      Mapped[str]      = mapped_column(String(50))
    environment: Mapped[str]      = mapped_column(String(20))
    org_id:      Mapped[str]      = mapped_column(String(100), default="default")
    timestamp:   Mapped[datetime] = mapped_column(DateTime, index=True)
    raw_payload: Mapped[Any]      = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_signals_service_ts", "service", "timestamp"),
        Index("ix_signals_metric_ts", "metric_name", "timestamp"),
    )


# ── Actions ────────────────────────────────────────────────────────────────

class Action(Base):
    __tablename__ = "actions"

    id:          Mapped[str]           = mapped_column(String(36), primary_key=True)
    incident_id: Mapped[str|None]      = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True)
    action_type: Mapped[str]           = mapped_column(String(80))
    status:      Mapped[str]           = mapped_column(String(20))   # success/failed/skipped
    target:      Mapped[str]           = mapped_column(String(200))
    parameters:  Mapped[Any]           = mapped_column(JSON, nullable=True)
    executed_at: Mapped[datetime]      = mapped_column(DateTime, index=True)
    result:      Mapped[Any]           = mapped_column(JSON, nullable=True)

    incident: Mapped["Incident | None"] = relationship("Incident", back_populates="actions")


# ── Learning ───────────────────────────────────────────────────────────────

class LearnOutcome(Base):
    __tablename__ = "learn_outcomes"

    id:               Mapped[str]      = mapped_column(String(36), primary_key=True)
    incident_id:      Mapped[str|None] = mapped_column(String(36), nullable=True, index=True)
    action_type:      Mapped[str]      = mapped_column(String(80), index=True)
    service:          Mapped[str]      = mapped_column(String(100), index=True)
    severity:         Mapped[str]      = mapped_column(String(10))
    outcome:          Mapped[str]      = mapped_column(String(20))   # success/failed
    confidence_delta: Mapped[float]    = mapped_column(Float, default=0.0)
    recorded_at:      Mapped[datetime] = mapped_column(DateTime, index=True)


class Recommendation(Base):
    __tablename__ = "recommendations"

    id:             Mapped[str]      = mapped_column(String(36), primary_key=True)
    service:        Mapped[str]      = mapped_column(String(100), index=True)
    action_type:    Mapped[str]      = mapped_column(String(80))
    confidence:     Mapped[float]    = mapped_column(Float)
    rationale:      Mapped[str]      = mapped_column(Text)
    status:         Mapped[str]      = mapped_column(String(20), default="pending")  # pending/applied/dismissed
    created_at:     Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ── Integrations ───────────────────────────────────────────────────────────

class Integration(Base):
    __tablename__ = "integrations"

    id:            Mapped[str]           = mapped_column(String(36), primary_key=True)
    name:          Mapped[str]           = mapped_column(String(100), unique=True)
    type:          Mapped[str]           = mapped_column(String(50))  # jira/slack/pagerduty/prometheus/datadog/cloudwatch
    status:        Mapped[str]           = mapped_column(String(20))  # connected/disconnected/error
    config:        Mapped[Any]           = mapped_column(JSON, nullable=True)
    last_synced_at:Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    created_at:    Mapped[datetime]      = mapped_column(DateTime, default=datetime.utcnow)


# ── Infrastructure ─────────────────────────────────────────────────────────

class ClusterInventory(Base):
    __tablename__ = "cluster_inventory"

    id:              Mapped[str]      = mapped_column(String(36), primary_key=True)
    cluster_name:    Mapped[str]      = mapped_column(String(150), unique=True)
    region:          Mapped[str]      = mapped_column(String(50))
    environment:     Mapped[str]      = mapped_column(String(20))
    status:          Mapped[str]      = mapped_column(String(20))   # healthy/degraded/unreachable
    node_count:      Mapped[int]      = mapped_column(Integer, default=0)
    namespace_count: Mapped[int]      = mapped_column(Integer, default=0)
    pod_count:       Mapped[int]      = mapped_column(Integer, default=0)
    unhealthy_pods:  Mapped[Any]      = mapped_column(JSON, nullable=True)
    last_checked_at: Mapped[datetime] = mapped_column(DateTime)


# ── Pullers ────────────────────────────────────────────────────────────────

class PullerRun(Base):
    __tablename__ = "puller_runs_db"

    id:             Mapped[str]           = mapped_column(String(36), primary_key=True)
    source:         Mapped[str]           = mapped_column(String(50), index=True)
    status:         Mapped[str]           = mapped_column(String(20))  # success/failed/partial
    records_pulled: Mapped[int]           = mapped_column(Integer, default=0)
    started_at:     Mapped[datetime]      = mapped_column(DateTime, index=True)
    completed_at:   Mapped[datetime|None] = mapped_column(DateTime, nullable=True)
    error_message:  Mapped[str|None]      = mapped_column(Text, nullable=True)


# ── Near Misses ────────────────────────────────────────────────────────────

class NearMiss(Base):
    __tablename__ = "near_misses"

    id:          Mapped[str]      = mapped_column(String(36), primary_key=True)
    service:     Mapped[str]      = mapped_column(String(100), index=True)
    region:      Mapped[str]      = mapped_column(String(50))
    metric_name: Mapped[str]      = mapped_column(String(100))
    peak_value:  Mapped[float]    = mapped_column(Float)
    threshold:   Mapped[float]    = mapped_column(Float)
    gap_percent: Mapped[float]    = mapped_column(Float)
    detected_at: Mapped[datetime] = mapped_column(DateTime, index=True)


# ── Golden Signals ─────────────────────────────────────────────────────────

class ServiceMetricBaseline(Base):
    """Rolling baseline for a service+metric combination, time-of-day aware."""
    __tablename__ = "service_metric_baselines"

    id:           Mapped[str]      = mapped_column(String(36), primary_key=True)
    service:      Mapped[str]      = mapped_column(String(100), index=True)
    metric_name:  Mapped[str]      = mapped_column(String(100), index=True)
    hour_of_day:  Mapped[int]      = mapped_column(Integer)
    day_of_week:  Mapped[int]      = mapped_column(Integer)
    mean:         Mapped[float]    = mapped_column(Float)
    stddev:       Mapped[float]    = mapped_column(Float, default=0.0)
    p50:          Mapped[float]    = mapped_column(Float, default=0.0)
    p95:          Mapped[float]    = mapped_column(Float, default=0.0)
    p99:          Mapped[float]    = mapped_column(Float, default=0.0)
    sample_count: Mapped[int]      = mapped_column(Integer, default=0)
    window_days:  Mapped[int]      = mapped_column(Integer, default=7)
    org_id:       Mapped[str]      = mapped_column(String(100), default="default")
    computed_at:  Mapped[datetime] = mapped_column(DateTime, index=True)

    __table_args__ = (
        Index("ix_baseline_service_metric_hour",
              "service", "metric_name", "hour_of_day", "day_of_week"),
    )


class ServiceEdgeMetric(Base):
    """RED metrics per service-to-service edge."""
    __tablename__ = "service_edge_metrics"

    id:             Mapped[str]      = mapped_column(String(36), primary_key=True)
    source_service: Mapped[str]      = mapped_column(String(100), index=True)
    dest_service:   Mapped[str]      = mapped_column(String(100), index=True)
    cluster:        Mapped[str]      = mapped_column(String(150), default="default")
    timestamp:      Mapped[datetime] = mapped_column(DateTime, index=True)
    p50_ms:         Mapped[float]    = mapped_column(Float, default=0.0)
    p95_ms:         Mapped[float]    = mapped_column(Float, default=0.0)
    p99_ms:         Mapped[float]    = mapped_column(Float, default=0.0)
    rps:            Mapped[float]    = mapped_column(Float, default=0.0)
    error_rate:     Mapped[float]    = mapped_column(Float, default=0.0)
    org_id:         Mapped[str]      = mapped_column(String(100), default="default")
    # HAProxy timing breakdown (Tq=queue, Tc=connect, Tr=backend, Tt=total)
    queue_time_ms:      Mapped[float] = mapped_column(Float, default=0.0)   # Tq
    connect_time_ms:    Mapped[float] = mapped_column(Float, default=0.0)   # Tc
    backend_time_ms:    Mapped[float] = mapped_column(Float, default=0.0)   # Tr
    total_time_ms:      Mapped[float] = mapped_column(Float, default=0.0)   # Tt
    active_connections: Mapped[int]   = mapped_column(Integer, default=0)

    __table_args__ = (
        Index("ix_edge_source_dest_ts",
              "source_service", "dest_service", "timestamp"),
    )

