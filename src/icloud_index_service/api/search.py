from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from icloud_index_service.api.security import require_plugin_api_token
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


def _get_search_session(
    session: Session = Depends(get_session),
) -> Generator[Session, None, None]:
    try:
        yield session
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


@router.get(
    "",
    dependencies=[Depends(_ensure_search_database_available), Depends(require_plugin_api_token)],
)
def search(
    query: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    path_scope: str | None = Query(default=None),
    session: Session = Depends(_get_search_session),
) -> dict[str, object]:
    try:
        payload = {
            "query": query,
            "limit": limit,
            "results": search_files(
                session,
                query=query,
                limit=limit,
                path_scope=path_scope,
            ),
        }
        if path_scope is not None:
            payload["path_scope"] = path_scope
        return payload
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=build_database_unavailable_detail(
                operation="search",
                startup_validation_error=str(exc),
            ),
        ) from exc
