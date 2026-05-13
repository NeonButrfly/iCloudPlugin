from __future__ import annotations

from sqlalchemy import ForeignKey, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "uq_jobs_active_metadata_refresh",
            "job_type",
            unique=True,
            sqlite_where=text(
                "job_type = 'metadata-refresh' AND status IN ('queued', 'running')"
            ),
            postgresql_where=text(
                "job_type = 'metadata-refresh' AND status IN ('queued', 'running')"
            ),
        ),
    )

    job_type: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, default=None)
    error_message: Mapped[str | None] = mapped_column(Text, default=None)
    sync_run_id: Mapped[int | None] = mapped_column(ForeignKey("sync_runs.id"), default=None)
