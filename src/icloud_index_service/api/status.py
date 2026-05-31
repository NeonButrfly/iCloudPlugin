from __future__ import annotations

import os
from collections.abc import Generator

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from icloud_index_service.api.security import require_plugin_api_token
from icloud_index_service.db import get_session
from icloud_index_service.services.auth_session_manager import (
    DEFAULT_AUTH_SESSION_STATE,
    build_auth_status_payload,
)
from icloud_index_service.services.product_readiness import (
    DEFAULT_REPO_ROOT,
    build_live_product_readiness_payload,
)
from icloud_index_service.services.search_service import build_database_unavailable_detail
from icloud_index_service.services.status_service import build_status_summary

router = APIRouter(prefix="/status", tags=["status"])


def _ensure_status_database_available(request: Request) -> None:
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
            operation="status",
            startup_validation_error=startup_validation_error,
        ),
    )


def _get_status_session(
    session: Session = Depends(get_session),
) -> Generator[Session, None, None]:
    try:
        yield session
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


@router.get(
    "/summary",
    dependencies=[Depends(_ensure_status_database_available), Depends(require_plugin_api_token)],
)
def get_status_summary(
    request: Request,
    session: Session = Depends(_get_status_session),
) -> dict[str, object]:
    database_state = "ok"
    startup_validation_error = None
    session_state = getattr(
        request.app.state,
        "auth_session_state",
        DEFAULT_AUTH_SESSION_STATE,
    )
    try:
        return build_status_summary(
            session,
            service_health={"status": "ok", "database": "ok"},
            auth_status=build_auth_status_payload(
                session_state=session_state,
                database_state=database_state,
                startup_validation_error=startup_validation_error,
            ),
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=build_database_unavailable_detail(
                operation="status",
                startup_validation_error=str(exc),
            ),
        ) from exc


@router.get(
    "/readiness",
    dependencies=[Depends(_ensure_status_database_available), Depends(require_plugin_api_token)],
)
def get_product_readiness(
    request: Request,
    session: Session = Depends(_get_status_session),
) -> dict[str, object]:
    database_state = "ok"
    startup_validation_error = None
    session_state = getattr(
        request.app.state,
        "auth_session_state",
        DEFAULT_AUTH_SESSION_STATE,
    )
    try:
        status_summary = build_status_summary(
            session,
            service_health={"status": "ok", "database": "ok"},
            auth_status=build_auth_status_payload(
                session_state=session_state,
                database_state=database_state,
                startup_validation_error=startup_validation_error,
            ),
        )
        return build_live_product_readiness_payload(
            repo_root=DEFAULT_REPO_ROOT,
            status_summary=status_summary,
            cloudflare_api_token_present=bool((os.getenv("CLOUDFLARE_API_TOKEN") or "").strip()),
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail=build_database_unavailable_detail(
                operation="status",
                startup_validation_error=str(exc),
            ),
        ) from exc
