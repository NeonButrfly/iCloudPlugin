"""repair dedupe workflow schema drift

Revision ID: 0009_repair_dedupe_workflow_schema
Revises: 0008_cloud_vault_tasks
Create Date: 2026-07-04 11:25:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_repair_dedupe_workflow_schema"
down_revision = "0008_cloud_vault_tasks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dedupe_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("strategy", sa.String(length=50), nullable=False),
        sa.Column("namespaces_json", sa.Text(), nullable=False),
        sa.Column("chunk_size", sa.Integer(), nullable=False),
        sa.Column("path_scope", sa.Text(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("max_groups", sa.Integer(), nullable=True),
        sa.Column("total_candidates", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("remaining_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("groups_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("state_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
    )

    with op.batch_alter_table("dedupe_groups") as batch_op:
        batch_op.add_column(sa.Column("dedupe_job_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("strategy", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("total_size_bytes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("recommended_keep_file_record_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("reason", sa.Text(), nullable=True))
        batch_op.create_foreign_key("fk_dedupe_groups_dedupe_job_id", "dedupe_jobs", ["dedupe_job_id"], ["id"])
        batch_op.create_foreign_key(
            "fk_dedupe_groups_recommended_keep_file_record_id",
            "files",
            ["recommended_keep_file_record_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("dedupe_groups") as batch_op:
        batch_op.drop_constraint("fk_dedupe_groups_recommended_keep_file_record_id", type_="foreignkey")
        batch_op.drop_constraint("fk_dedupe_groups_dedupe_job_id", type_="foreignkey")
        batch_op.drop_column("reason")
        batch_op.drop_column("confidence")
        batch_op.drop_column("recommended_keep_file_record_id")
        batch_op.drop_column("total_size_bytes")
        batch_op.drop_column("strategy")
        batch_op.drop_column("dedupe_job_id")

    op.drop_table("dedupe_jobs")
