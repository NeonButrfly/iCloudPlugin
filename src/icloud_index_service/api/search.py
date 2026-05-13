from __future__ import annotations

from collections.abc import Generator
import inspect

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from icloud_index_service.db import get_session
from icloud_index_service.services.search_service import (
    build_database_unavailable_detail,
    search_files,
)

router = APIRouter(prefix="/search", tags=["search"])


def _ensure_search_database_available(request: Request) -> None:
    database_healthcheck = getattr(request.app.state, "database_healthcheck", None)
    database_state = getattr(request.app.state, "database_startup_status", None)
    if callable(database_healthcheck):
        try:
            database_state = "ok" if database_healthcheck() else "unavailable"
        except Exception:
            database_state = "unavailable"

    if database_state == "ok":
        return

    startup_validation_error = getattr(request.app.state, "database_startup_error", None)
    raise HTTPException(
        status_code=503,
        detail=build_database_unavailable_detail(
            operation="search",
            startup_validation_error=startup_validation_error,
        ),
    )


def _get_search_session(request: Request) -> Generator[Session, None, None]:
    _ensure_search_database_available(request)
    session_provider = request.app.dependency_overrides.get(get_session, get_session)
    provided_session = session_provider()
    if inspect.isgenerator(provided_session):
        try:
            yield next(provided_session)
        finally:
            try:
                next(provided_session)
            except StopIteration:
                pass
        return

    try:
        yield provided_session
    finally:
        close = getattr(provided_session, "close", None)
        if callable(close):
            close()


@router.get("")
def search(
    query: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(_get_search_session),
) -> dict[str, object]:
    try:
        return {
            "query": query,
            "limit": limit,
            "results": search_files(session, query=query, limit=limit),
        }
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=build_database_unavailable_detail(
                operation="search",
                startup_validation_error=str(exc),
            ),
        ) from exc
