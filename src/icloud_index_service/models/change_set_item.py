from __future__ import annotations

from sqlalchemy import ForeignKey, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base


class ChangeSetItem(Base):
    __tablename__ = "change_set_items"

    change_set_id: Mapped[int] = mapped_column(ForeignKey("change_sets.id"), nullable=False)
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    namespace: Mapped[str] = mapped_column(String(50), nullable=False)
    file_record_id: Mapped[int | None] = mapped_column(ForeignKey("files.id"), default=None)
    document_note_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("document_vault_notes.id"),
        default=None,
    )
    original_path: Mapped[str | None] = mapped_column(Text, default=None)
    result_path: Mapped[str | None] = mapped_column(Text, default=None)
    backup_path: Mapped[str | None] = mapped_column(Text, default=None)
    content_hash_before: Mapped[str | None] = mapped_column(String(128), default=None)
    content_hash_after: Mapped[str | None] = mapped_column(String(128), default=None)
    similarity_score: Mapped[float | None] = mapped_column(Float, default=None)
    restore_status: Mapped[str | None] = mapped_column(String(50), default=None)
    restore_error: Mapped[str | None] = mapped_column(Text, default=None)
