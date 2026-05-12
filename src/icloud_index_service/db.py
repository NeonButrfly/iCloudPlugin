from __future__ import annotations

from collections.abc import Generator
from functools import lru_cache
from typing import Any

from icloud_index_service.config import get_settings


@lru_cache
def get_engine() -> Any:
    from sqlalchemy import create_engine

    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def get_session_factory() -> Any:
    from sqlalchemy.orm import sessionmaker

    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def clear_database_caches() -> None:
    get_session_factory.cache_clear()
    get_engine.cache_clear()
    get_settings.cache_clear()


def validate_database_configuration() -> None:
    get_engine()


def get_session() -> Generator[Any, None, None]:
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def main() -> None:
    validate_database_configuration()


if __name__ == "__main__":
    main()
