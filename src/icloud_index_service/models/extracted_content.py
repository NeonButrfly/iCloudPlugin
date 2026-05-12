from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ExtractedContent(Base):
    __tablename__ = "extracted_contents"

    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128), default=None)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=utc_now,
        nullable=False,
    )
