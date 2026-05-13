"""track per-file sync progress

Revision ID: 0003_file_sync_progress
Revises: 0002_active_refresh_unique_index
Create Date: 2026-05-13 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0003_file_sync_progress"
down_revision = "0002_active_refresh_unique_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "files",
        sa.Column("last_seen_sync_run_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_files_last_seen_sync_run_id",
        "files",
        "sync_runs",
        ["last_seen_sync_run_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_files_last_seen_sync_run_id", "files", type_="foreignkey")
    op.drop_column("files", "last_seen_sync_run_id")
