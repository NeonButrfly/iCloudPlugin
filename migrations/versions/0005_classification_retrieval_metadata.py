"""add retrieval metadata to classification states

Revision ID: 0005_classification_retrieval_metadata
Revises: 0004_classification_jobs
Create Date: 2026-05-26 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0005_classification_retrieval_metadata"
down_revision = "0004_classification_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("classification_states", sa.Column("entity_summary", sa.Text(), nullable=True))
    op.add_column("classification_states", sa.Column("topic_summary", sa.Text(), nullable=True))
    op.add_column("classification_states", sa.Column("retrieval_terms_json", sa.Text(), nullable=True))
    op.add_column("classification_states", sa.Column("retrieval_text", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("classification_states", "retrieval_text")
    op.drop_column("classification_states", "retrieval_terms_json")
    op.drop_column("classification_states", "topic_summary")
    op.drop_column("classification_states", "entity_summary")
