from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base


class ClassificationState(Base):
    __tablename__ = "classification_states"

    file_id: Mapped[int] = mapped_column(ForeignKey("files.id"), nullable=False, unique=True)
    submission_status: Mapped[str] = mapped_column(String(50), nullable=False)
    source_fingerprint: Mapped[str | None] = mapped_column(String(128), default=None)
    source_size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    source_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    last_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    classifier_note_path: Mapped[str | None] = mapped_column(Text, default=None)
    classifier_manifest_record: Mapped[str | None] = mapped_column(Text, default=None)
    primary_label: Mapped[str | None] = mapped_column(String(255), default=None)
    summary: Mapped[str | None] = mapped_column(Text, default=None)
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    reasoning: Mapped[str | None] = mapped_column(Text, default=None)
    response_payload_json: Mapped[str | None] = mapped_column(Text, default=None)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
