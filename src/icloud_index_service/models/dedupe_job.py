from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base, utc_now


class DedupeJob(Base):
    __tablename__ = "dedupe_jobs"

    job_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    namespaces_json: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_size: Mapped[int] = mapped_column(nullable=False)
    path_scope: Mapped[str | None] = mapped_column(Text, default=None)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_groups: Mapped[int | None] = mapped_column(default=None)
    total_candidates: Mapped[int] = mapped_column(default=0, nullable=False)
    processed_count: Mapped[int] = mapped_column(default=0, nullable=False)
    remaining_count: Mapped[int] = mapped_column(default=0, nullable=False)
    groups_found: Mapped[int] = mapped_column(default=0, nullable=False)
    state_json: Mapped[str | None] = mapped_column(Text, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    started_at: Mapped[datetime] = mapped_column(
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
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
