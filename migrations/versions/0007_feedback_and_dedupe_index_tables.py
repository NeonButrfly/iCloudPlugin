"""add manual feedback and dedupe index tables

Revision ID: 0007_feedback_and_dedupe_index_tables
Revises: 0006_vault_mutation_index_tables
Create Date: 2026-07-02 13:15:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_feedback_and_dedupe_index_tables"
down_revision = "0006_vault_mutation_index_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "manual_feedback_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("source_file_record_id", sa.Integer(), nullable=True),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("old_value_json", sa.Text(), nullable=True),
        sa.Column("new_value_json", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("feedback_strength", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["note_id"], ["document_vault_notes.id"]),
        sa.ForeignKeyConstraint(["source_file_record_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
    )
    op.create_table(
        "dedupe_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dedupe_group_id", sa.String(length=64), nullable=False),
        sa.Column("group_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("canonical_item_path", sa.Text(), nullable=False),
        sa.Column("canonical_file_record_id", sa.Integer(), nullable=True),
        sa.Column("duplicate_count", sa.Integer(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("change_set_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["canonical_file_record_id"], ["files.id"]),
        sa.ForeignKeyConstraint(["change_set_id"], ["change_sets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_group_id"),
    )
    op.create_table(
        "dedupe_group_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("dedupe_group_id", sa.Integer(), nullable=False),
        sa.Column("file_record_id", sa.Integer(), nullable=True),
        sa.Column("path_at_analysis_time", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("decision_role", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["dedupe_group_id"], ["dedupe_groups.id"]),
        sa.ForeignKeyConstraint(["file_record_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("dedupe_group_items")
    op.drop_table("dedupe_groups")
    op.drop_table("manual_feedback_events")
