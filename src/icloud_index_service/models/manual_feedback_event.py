from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base, utc_now


class ManualFeedbackEvent(Base):
    __tablename__ = "manual_feedback_events"

    event_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    note_id: Mapped[int] = mapped_column(ForeignKey("document_vault_notes.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    feedback_strength: Mapped[str] = mapped_column(String(50), nullable=False)
    source_file_record_id: Mapped[int | None] = mapped_column(ForeignKey("files.id"), default=None)
    old_value_json: Mapped[str | None] = mapped_column(Text, default=None)
    new_value_json: Mapped[str | None] = mapped_column(Text, default=None)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=utc_now,
        server_default=func.now(),
        nullable=False,
    )
