from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from icloud_index_service.models.base import Base, utc_now


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    account_identifier: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    session_state: Mapped[str] = mapped_column(String(50), nullable=False)
    dsid: Mapped[str | None] = mapped_column(String(255), default=None, unique=True)
    cookies_json: Mapped[str | None] = mapped_column(Text, default=None)
    refreshed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=utc_now,
        server_default=func.now(),
        nullable=False,
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
