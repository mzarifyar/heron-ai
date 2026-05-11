"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-05-08
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("title", sa.String(500)),
        sa.Column("severity", sa.String(10), index=True),
        sa.Column("status", sa.String(20), index=True),
        sa.Column("service", sa.String(100), index=True),
        sa.Column("region", sa.String(50)),
        sa.Column("environment", sa.String(20)),
        sa.Column("org_id", sa.String(100), index=True),
        sa.Column("started_at", sa.DateTime, index=True),
        sa.Column("resolved_at", sa.DateTime, nullable=True),
        sa.Column("duration_seconds", sa.Integer, nullable=True),
        sa.Column("auto_healed", sa.Boolean, default=False),
        sa.Column("mttr_seconds", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )
    op.create_index("ix_incidents_started_status", "incidents", ["started_at", "status"])
    op.create_index("ix_incidents_org_service", "incidents", ["org_id", "service"])

    op.create_table(
        "incident_timeline",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("incidents.id", ondelete="CASCADE"), index=True),
        sa.Column("event_type", sa.String(80)),
        sa.Column("description", sa.Text),
        sa.Column("actor", sa.String(50)),
        sa.Column("severity", sa.String(20)),
        sa.Column("timestamp", sa.DateTime, index=True),
        sa.Column("metadata", sa.JSON, nullable=True),
    )

    op.create_table(
        "incident_annotations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("incidents.id", ondelete="CASCADE"), index=True),
        sa.Column("author", sa.String(120)),
        sa.Column("content", sa.Text),
        sa.Column("created_at", sa.DateTime),
    )

    op.create_table(
        "postmortems",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("incidents.id", ondelete="CASCADE"), unique=True),
        sa.Column("content", sa.Text),
        sa.Column("author", sa.String(120)),
        sa.Column("created_at", sa.DateTime),
        sa.Column("updated_at", sa.DateTime),
    )

    op.create_table(
        "signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(50)),
        sa.Column("metric_name", sa.String(100), index=True),
        sa.Column("value", sa.Float),
        sa.Column("severity", sa.String(20)),
        sa.Column("service", sa.String(100), index=True),
        sa.Column("region", sa.String(50)),
        sa.Column("environment", sa.String(20)),
        sa.Column("org_id", sa.String(100)),
        sa.Column("timestamp", sa.DateTime, index=True),
        sa.Column("raw_payload", sa.JSON, nullable=True),
    )
    op.create_index("ix_signals_service_ts", "signals", ["service", "timestamp"])
    op.create_index("ix_signals_metric_ts", "signals", ["metric_name", "timestamp"])

    op.create_table(
        "actions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), sa.ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("action_type", sa.String(80)),
        sa.Column("status", sa.String(20)),
        sa.Column("target", sa.String(200)),
        sa.Column("parameters", sa.JSON, nullable=True),
        sa.Column("executed_at", sa.DateTime, index=True),
        sa.Column("result", sa.JSON, nullable=True),
    )

    op.create_table(
        "learn_outcomes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("incident_id", sa.String(36), nullable=True, index=True),
        sa.Column("action_type", sa.String(80), index=True),
        sa.Column("service", sa.String(100), index=True),
        sa.Column("severity", sa.String(10)),
        sa.Column("outcome", sa.String(20)),
        sa.Column("confidence_delta", sa.Float),
        sa.Column("recorded_at", sa.DateTime, index=True),
    )

    op.create_table(
        "recommendations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("service", sa.String(100), index=True),
        sa.Column("action_type", sa.String(80)),
        sa.Column("confidence", sa.Float),
        sa.Column("rationale", sa.Text),
        sa.Column("status", sa.String(20)),
        sa.Column("created_at", sa.DateTime),
    )

    op.create_table(
        "integrations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(100), unique=True),
        sa.Column("type", sa.String(50)),
        sa.Column("status", sa.String(20)),
        sa.Column("config", sa.JSON, nullable=True),
        sa.Column("last_synced_at", sa.DateTime, nullable=True),
        sa.Column("created_at", sa.DateTime),
    )

    op.create_table(
        "cluster_inventory",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cluster_name", sa.String(150), unique=True),
        sa.Column("region", sa.String(50)),
        sa.Column("environment", sa.String(20)),
        sa.Column("status", sa.String(20)),
        sa.Column("node_count", sa.Integer),
        sa.Column("namespace_count", sa.Integer),
        sa.Column("pod_count", sa.Integer),
        sa.Column("unhealthy_pods", sa.JSON, nullable=True),
        sa.Column("last_checked_at", sa.DateTime),
    )

    op.create_table(
        "puller_runs_db",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.String(50), index=True),
        sa.Column("status", sa.String(20)),
        sa.Column("records_pulled", sa.Integer),
        sa.Column("started_at", sa.DateTime, index=True),
        sa.Column("completed_at", sa.DateTime, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
    )

    op.create_table(
        "near_misses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("service", sa.String(100), index=True),
        sa.Column("region", sa.String(50)),
        sa.Column("metric_name", sa.String(100)),
        sa.Column("peak_value", sa.Float),
        sa.Column("threshold", sa.Float),
        sa.Column("gap_percent", sa.Float),
        sa.Column("detected_at", sa.DateTime, index=True),
    )


def downgrade() -> None:
    for tbl in [
        "near_misses", "puller_runs_db", "cluster_inventory", "integrations",
        "recommendations", "learn_outcomes", "actions", "signals",
        "postmortems", "incident_annotations", "incident_timeline", "incidents",
    ]:
        op.drop_table(tbl)
