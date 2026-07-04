from __future__ import annotations

from sqlalchemy import Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base


class DedupeGroupItem(Base):
    __tablename__ = "dedupe_group_items"

    dedupe_group_id: Mapped[int] = mapped_column(ForeignKey("dedupe_groups.id"), nullable=False)
    path_at_analysis_time: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    decision_role: Mapped[str] = mapped_column(String(50), nullable=False)
    file_record_id: Mapped[int | None] = mapped_column(ForeignKey("files.id"), default=None)
    size_bytes: Mapped[int | None] = mapped_column(default=None)
    similarity_score: Mapped[float | None] = mapped_column(Float, default=None)
    source_exists: Mapped[bool | None] = mapped_column(default=None)
