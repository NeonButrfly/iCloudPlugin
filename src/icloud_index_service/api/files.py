from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from icloud_index_service.db import get_session
from icloud_index_service.services.search_service import (
    build_database_unavailable_detail,
    get_file_details,
)

router = APIRouter(prefix="/files", tags=["files"])


def _ensure_files_database_available(request: Request) -> None:
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
            operation="files",
            startup_validation_error=startup_validation_error,
        ),
    )


def _get_files_session(
    session: Session = Depends(get_session),
) -> Generator[Session, None, None]:
    try:
        yield session
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


@router.get("/{file_id}", dependencies=[Depends(_ensure_files_database_available)])
def get_file(
    file_id: int,
    session: Session = Depends(_get_files_session),
) -> dict[str, object]:
    try:
        payload = get_file_details(session, file_id=file_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=build_database_unavailable_detail(
                operation="files",
                startup_validation_error=str(exc),
            ),
        ) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="File not found")
    return payload
