"""widen files external_id for long paths

Revision ID: 0012_widen_files_external_id_for_long_paths
Revises: 0011_promote_dedupe_size_columns_to_bigint
Create Date: 2026-07-10 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0012_widen_files_external_id_for_long_paths"
down_revision = "0011_promote_dedupe_size_columns_to_bigint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "files",
        "external_id",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "files",
        "external_id",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
