from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base, utc_now


class CloudVaultTask(Base):
    __tablename__ = "cloud_vault_tasks"
    __table_args__ = (
        Index("ix_cloud_vault_tasks_status_updated_at", "status", "updated_at"),
        Index("ix_cloud_vault_tasks_task_type_status", "task_type", "status"),
    )

    task_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    input_json: Mapped[str] = mapped_column(Text, nullable=False)
    result_json: Mapped[str | None] = mapped_column(Text, default=None)
    progress_json: Mapped[str | None] = mapped_column(Text, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), default=None, unique=True)
    parent_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("cloud_vault_tasks.id"),
        default=None,
    )
    change_set_id: Mapped[str | None] = mapped_column(String(64), default=None)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
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
