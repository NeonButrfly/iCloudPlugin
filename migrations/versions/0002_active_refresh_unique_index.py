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
    op.execute(
        sa.text(
            """
            WITH ranked_active_jobs AS (
                SELECT
                    id,
                    ROW_NUMBER() OVER (
                        ORDER BY CASE WHEN status = 'running' THEN 0 ELSE 1 END, id
                    ) AS rank_num
                FROM jobs
                WHERE job_type = 'metadata-refresh'
                  AND status IN ('queued', 'running')
            )
            UPDATE jobs
            SET
                status = 'failed',
                error_message = CASE
                    WHEN error_message IS NULL OR error_message = '' THEN
                        'Marked failed during 0002_active_refresh_unique_index migration to deduplicate active metadata-refresh jobs.'
                    ELSE
                        error_message || ' Marked failed during 0002_active_refresh_unique_index migration to deduplicate active metadata-refresh jobs.'
                END
            WHERE id IN (
                SELECT id
                FROM ranked_active_jobs
                WHERE rank_num > 1
            )
            """
        )
    )
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
