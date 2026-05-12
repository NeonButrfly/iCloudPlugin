from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from icloud_index_service.db import validate_database_configuration


def should_skip_database_startup_validation() -> bool:
    raw = os.getenv("ICLOUD_INDEX_SKIP_DB_STARTUP_VALIDATION", "")
    return raw.lower() in {"1", "true", "yes", "on"}


@asynccontextmanager
async def lifespan(_: FastAPI):
    if not should_skip_database_startup_validation():
        validate_database_configuration()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
