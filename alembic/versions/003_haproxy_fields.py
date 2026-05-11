"""Add HAProxy timing fields to service_edge_metrics

Revision ID: 003
Revises: 002
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("service_edge_metrics") as batch:
        batch.add_column(sa.Column("queue_time_ms",      sa.Float(), nullable=True, server_default="0"))
        batch.add_column(sa.Column("connect_time_ms",    sa.Float(), nullable=True, server_default="0"))
        batch.add_column(sa.Column("backend_time_ms",    sa.Float(), nullable=True, server_default="0"))
        batch.add_column(sa.Column("total_time_ms",      sa.Float(), nullable=True, server_default="0"))
        batch.add_column(sa.Column("active_connections", sa.Integer(), nullable=True, server_default="0"))


def downgrade() -> None:
    with op.batch_alter_table("service_edge_metrics") as batch:
        for col in ["queue_time_ms", "connect_time_ms", "backend_time_ms",
                    "total_time_ms", "active_connections"]:
            batch.drop_column(col)
