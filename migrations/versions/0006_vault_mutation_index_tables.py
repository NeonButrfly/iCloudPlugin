"""add vault mutation and note inventory tables

Revision ID: 0006_vault_mutation_index_tables
Revises: 0005_classification_retrieval_metadata
Create Date: 2026-07-02 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0006_vault_mutation_index_tables"
down_revision = "0005_classification_retrieval_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "change_sets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("change_set_id", sa.String(length=64), nullable=False),
        sa.Column("operation_type", sa.String(length=50), nullable=False),
        sa.Column("namespace", sa.String(length=50), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=50), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("parent_change_set_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("change_set_id"),
    )
    op.create_table(
        "document_vault_notes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("visible_title", sa.String(length=512), nullable=False),
        sa.Column("note_type", sa.String(length=100), nullable=False),
        sa.Column("frontmatter_json", sa.Text(), nullable=True),
        sa.Column("canonical_source_path", sa.Text(), nullable=True),
        sa.Column("source_file_record_id", sa.Integer(), nullable=True),
        sa.Column("attachment_mode", sa.String(length=100), nullable=True),
        sa.Column("source_link", sa.Text(), nullable=True),
        sa.Column("primary_label", sa.String(length=255), nullable=True),
        sa.Column("secondary_labels_json", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_generated", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.ForeignKeyConstraint(["source_file_record_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("relative_path"),
    )
    op.create_table(
        "change_set_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("change_set_id", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=50), nullable=False),
        sa.Column("namespace", sa.String(length=50), nullable=False),
        sa.Column("file_record_id", sa.Integer(), nullable=True),
        sa.Column("document_note_record_id", sa.Integer(), nullable=True),
        sa.Column("original_path", sa.Text(), nullable=True),
        sa.Column("result_path", sa.Text(), nullable=True),
        sa.Column("backup_path", sa.Text(), nullable=True),
        sa.Column("content_hash_before", sa.String(length=128), nullable=True),
        sa.Column("content_hash_after", sa.String(length=128), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("restore_status", sa.String(length=50), nullable=True),
        sa.Column("restore_error", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["change_set_id"], ["change_sets.id"]),
        sa.ForeignKeyConstraint(["document_note_record_id"], ["document_vault_notes.id"]),
        sa.ForeignKeyConstraint(["file_record_id"], ["files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("change_set_items")
    op.drop_table("document_vault_notes")
    op.drop_table("change_sets")
