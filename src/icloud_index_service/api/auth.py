from __future__ import annotations

from fastapi import APIRouter, Request

from icloud_index_service.services.auth_session_manager import (
    DEFAULT_AUTH_SESSION_STATE,
    build_auth_status_payload,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
def auth_status(request: Request) -> dict[str, str]:
    session_state = getattr(
        request.app.state,
        "auth_session_state",
        DEFAULT_AUTH_SESSION_STATE,
    )
    database_healthcheck = getattr(request.app.state, "database_healthcheck", None)
    database_state = getattr(request.app.state, "database_startup_status", None)
    if callable(database_healthcheck):
        database_state = "ok" if database_healthcheck() else "unavailable"
    startup_validation_error = getattr(request.app.state, "database_startup_error", None)
    return build_auth_status_payload(
        session_state=session_state,
        database_state=database_state,
        startup_validation_error=startup_validation_error,
    )
