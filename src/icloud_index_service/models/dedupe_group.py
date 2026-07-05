from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base, utc_now


class DedupeGroup(Base):
    __tablename__ = "dedupe_groups"

    dedupe_group_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    group_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    canonical_item_path: Mapped[str] = mapped_column(Text, nullable=False)
    duplicate_count: Mapped[int] = mapped_column(nullable=False)
    dedupe_job_id: Mapped[int | None] = mapped_column(ForeignKey("dedupe_jobs.id"), default=None)
    strategy: Mapped[str | None] = mapped_column(String(50), default=None)
    total_size_bytes: Mapped[int | None] = mapped_column(BigInteger, default=None)
    canonical_file_record_id: Mapped[int | None] = mapped_column(ForeignKey("files.id"), default=None)
    recommended_keep_file_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("files.id"),
        default=None,
    )
    confidence: Mapped[float | None] = mapped_column(Float, default=None)
    reason: Mapped[str | None] = mapped_column(Text, default=None)
    evidence_json: Mapped[str | None] = mapped_column(Text, default=None)
    decision_notes: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    change_set_id: Mapped[int | None] = mapped_column(ForeignKey("change_sets.id"), default=None)
