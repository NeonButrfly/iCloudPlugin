"""add classification jobs, states, and file metadata

Revision ID: 0004_classification_jobs_and_file_metadata
Revises: 0003_file_sync_progress
Create Date: 2026-05-16 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0004_classification_jobs_and_file_metadata"
down_revision = "0003_file_sync_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("files", sa.Column("extension", sa.String(length=50), nullable=True))
    op.add_column("files", sa.Column("modified_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "classification_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=128), nullable=True),
        sa.Column("source_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submission_status", sa.String(length=50), nullable=False),
        sa.Column("last_submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classifier_note_path", sa.Text(), nullable=True),
        sa.Column("classifier_manifest_record", sa.Text(), nullable=True),
        sa.Column("primary_label", sa.String(length=255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("reasoning", sa.Text(), nullable=True),
        sa.Column("response_payload_json", sa.Text(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
        sa.UniqueConstraint("file_id"),
    )

    op.create_table(
        "classification_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("priority_bucket", sa.String(length=50), nullable=False),
        sa.Column("priority_rank", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("worker_id", sa.String(length=255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("classifier_response_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["file_id"], ["files.id"]),
    )
    op.create_index(
        "ix_classification_jobs_status_priority",
        "classification_jobs",
        ["status", "priority_rank", "id"],
    )
    op.create_index(
        "uq_classification_jobs_active_file",
        "classification_jobs",
        ["file_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
        sqlite_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_classification_jobs_active_file", table_name="classification_jobs")
    op.drop_index("ix_classification_jobs_status_priority", table_name="classification_jobs")
    op.drop_table("classification_jobs")
    op.drop_table("classification_states")
    op.drop_column("files", "modified_at")
    op.drop_column("files", "extension")
