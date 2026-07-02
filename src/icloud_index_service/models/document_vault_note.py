from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, false, func
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base, utc_now


class DocumentVaultNote(Base):
    __tablename__ = "document_vault_notes"

    relative_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    visible_title: Mapped[str] = mapped_column(String(512), nullable=False)
    note_type: Mapped[str] = mapped_column(String(100), nullable=False)
    frontmatter_json: Mapped[str | None] = mapped_column(Text, default=None)
    canonical_source_path: Mapped[str | None] = mapped_column(Text, default=None)
    source_file_record_id: Mapped[int | None] = mapped_column(ForeignKey("files.id"), default=None)
    attachment_mode: Mapped[str | None] = mapped_column(String(100), default=None)
    source_link: Mapped[str | None] = mapped_column(Text, default=None)
    primary_label: Mapped[str | None] = mapped_column(String(255), default=None)
    secondary_labels_json: Mapped[str | None] = mapped_column(Text, default=None)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    is_generated: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false(), nullable=False)
