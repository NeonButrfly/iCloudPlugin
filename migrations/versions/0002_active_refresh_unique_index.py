"""add active refresh unique index

Revision ID: 0002_active_refresh_unique_index
Revises: 0001_initial_schema
Create Date: 2026-05-12 00:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_active_refresh_unique_index"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_jobs_active_metadata_refresh",
        "jobs",
        ["job_type"],
        unique=True,
        sqlite_where=sa.text(
            "job_type = 'metadata-refresh' AND status IN ('queued', 'running')"
        ),
        postgresql_where=sa.text(
            "job_type = 'metadata-refresh' AND status IN ('queued', 'running')"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_jobs_active_metadata_refresh", table_name="jobs")
