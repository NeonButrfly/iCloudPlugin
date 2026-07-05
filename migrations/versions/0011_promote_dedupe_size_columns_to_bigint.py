"""promote dedupe size columns to bigint

Revision ID: 0011_promote_dedupe_size_columns_to_bigint
Revises: 0010_repair_dedupe_group_item_source_exists
Create Date: 2026-07-04 16:25:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_promote_dedupe_size_columns_to_bigint"
down_revision = "0010_repair_dedupe_group_item_source_exists"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("dedupe_groups") as batch_op:
        batch_op.alter_column(
            "total_size_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )

    with op.batch_alter_table("dedupe_group_items") as batch_op:
        batch_op.alter_column(
            "size_bytes",
            existing_type=sa.Integer(),
            type_=sa.BigInteger(),
            existing_nullable=True,
        )


def downgrade() -> None:
    with op.batch_alter_table("dedupe_group_items") as batch_op:
        batch_op.alter_column(
            "size_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )

    with op.batch_alter_table("dedupe_groups") as batch_op:
        batch_op.alter_column(
            "total_size_bytes",
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=True,
        )
