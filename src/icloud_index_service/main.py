from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from icloud_index_service.db import validate_database_configuration


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_database_configuration()
    yield


app = FastAPI(lifespan=lifespan)


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
