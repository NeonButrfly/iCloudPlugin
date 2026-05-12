from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import DeclarativeBase, Mapped, MappedAsDataclass, mapped_column


class Base(MappedAsDataclass, DeclarativeBase):
    id: Mapped[int] = mapped_column(init=False, primary_key=True)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
