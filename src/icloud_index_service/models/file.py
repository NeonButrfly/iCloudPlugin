from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, false
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base


class FileRecord(Base):
    __tablename__ = "files"

    external_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(512), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    extension: Mapped[str | None] = mapped_column(String(50), default=None)
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=false(),
        nullable=False,
    )
    size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_seen_sync_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("sync_runs.id"),
        default=None,
    )
