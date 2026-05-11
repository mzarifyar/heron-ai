"""Add golden signals tables

Revision ID: 002
Revises: 001
Create Date: 2026-05-10
"""
from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_metric_baselines",
        sa.Column("id",           sa.String(36),  primary_key=True),
        sa.Column("service",      sa.String(100), index=True),
        sa.Column("metric_name",  sa.String(100), index=True),
        sa.Column("hour_of_day",  sa.Integer()),
        sa.Column("day_of_week",  sa.Integer()),
        sa.Column("mean",         sa.Float()),
        sa.Column("stddev",       sa.Float(), default=0.0),
        sa.Column("p50",          sa.Float(), default=0.0),
        sa.Column("p95",          sa.Float(), default=0.0),
        sa.Column("p99",          sa.Float(), default=0.0),
        sa.Column("sample_count", sa.Integer(), default=0),
        sa.Column("window_days",  sa.Integer(), default=7),
        sa.Column("org_id",       sa.String(100), default="default"),
        sa.Column("computed_at",  sa.DateTime, index=True),
    )
    op.create_index(
        "ix_baseline_service_metric_hour",
        "service_metric_baselines",
        ["service", "metric_name", "hour_of_day", "day_of_week"],
    )

    op.create_table(
        "service_edge_metrics",
        sa.Column("id",             sa.String(36),  primary_key=True),
        sa.Column("source_service", sa.String(100), index=True),
        sa.Column("dest_service",   sa.String(100), index=True),
        sa.Column("cluster",        sa.String(150), default="default"),
        sa.Column("timestamp",      sa.DateTime,    index=True),
        sa.Column("p50_ms",         sa.Float(), default=0.0),
        sa.Column("p95_ms",         sa.Float(), default=0.0),
        sa.Column("p99_ms",         sa.Float(), default=0.0),
        sa.Column("rps",            sa.Float(), default=0.0),
        sa.Column("error_rate",     sa.Float(), default=0.0),
        sa.Column("org_id",         sa.String(100), default="default"),
    )
    op.create_index(
        "ix_edge_source_dest_ts",
        "service_edge_metrics",
        ["source_service", "dest_service", "timestamp"],
    )


def downgrade() -> None:
    op.drop_table("service_edge_metrics")
    op.drop_table("service_metric_baselines")
