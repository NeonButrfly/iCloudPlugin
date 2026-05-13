from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from icloud_index_service.api.auth import router as auth_router
from icloud_index_service.api.files import router as files_router
from icloud_index_service.api.refresh import router as refresh_router
from icloud_index_service.api.search import router as search_router
from icloud_index_service.db import validate_database_configuration
from icloud_index_service.services.auth_session_manager import (
    DEFAULT_AUTH_SESSION_STATE,
    detect_auth_session_state,
)


def initialize_runtime_state(app: FastAPI) -> None:
    if not hasattr(app.state, "auth_session_state"):
        app.state.auth_session_state = detect_auth_session_state()
    if not hasattr(app.state, "database_healthcheck"):
        app.state.database_healthcheck = lambda: check_database_health()
    if not hasattr(app.state, "database_startup_status"):
        app.state.database_startup_status = "unknown"
    if not hasattr(app.state, "database_startup_error"):
        app.state.database_startup_error = None


def format_startup_validation_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_runtime_state(app)
    try:
        validate_database_configuration()
    except Exception as exc:
        app.state.database_startup_status = "unavailable"
        app.state.database_startup_error = format_startup_validation_error(exc)
    else:
        app.state.database_startup_status = "ok"
        app.state.database_startup_error = None
    yield


app = FastAPI(lifespan=lifespan)
initialize_runtime_state(app)
app.include_router(auth_router)
app.include_router(files_router)
app.include_router(refresh_router)
app.include_router(search_router)


def check_database_health() -> bool:
    try:
        validate_database_configuration()
    except Exception:
        return False
    return True


@app.get("/health")
def health():
    if check_database_health():
        return {"status": "ok", "database": "ok"}
    return JSONResponse(
        status_code=503,
        content={"status": "degraded", "database": "unavailable"},
    )
