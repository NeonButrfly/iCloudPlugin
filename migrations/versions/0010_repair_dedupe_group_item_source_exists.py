"""repair dedupe group item source_exists column

Revision ID: 0010_repair_dedupe_group_item_source_exists
Revises: 0009_repair_dedupe_workflow_schema
Create Date: 2026-07-04 11:40:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0010_repair_dedupe_group_item_source_exists"
down_revision = "0009_repair_dedupe_workflow_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("dedupe_group_items") as batch_op:
        batch_op.add_column(sa.Column("source_exists", sa.Boolean(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("dedupe_group_items") as batch_op:
        batch_op.drop_column("source_exists")
