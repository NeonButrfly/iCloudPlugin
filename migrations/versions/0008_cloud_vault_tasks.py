"""add cloud vault task queue

Revision ID: 0008_cloud_vault_tasks
Revises: 0007_feedback_and_dedupe_index_tables
Create Date: 2026-07-04 13:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_cloud_vault_tasks"
down_revision = "0007_feedback_and_dedupe_index_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cloud_vault_tasks",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("task_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("progress_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("parent_task_id", sa.Integer(), nullable=True),
        sa.Column("change_set_id", sa.String(length=64), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["parent_task_id"], ["cloud_vault_tasks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.UniqueConstraint("task_id"),
    )
    op.create_index(
        "ix_cloud_vault_tasks_status_updated_at",
        "cloud_vault_tasks",
        ["status", "updated_at"],
        unique=False,
    )
    op.create_index(
        "ix_cloud_vault_tasks_task_type_status",
        "cloud_vault_tasks",
        ["task_type", "status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_cloud_vault_tasks_task_type_status", table_name="cloud_vault_tasks")
    op.drop_index("ix_cloud_vault_tasks_status_updated_at", table_name="cloud_vault_tasks")
    op.drop_table("cloud_vault_tasks")
