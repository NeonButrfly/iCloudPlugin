from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from icloud_index_service.api.security import require_plugin_api_token
from icloud_index_service.db import get_session
from icloud_index_service.services.job_runner import (
    SchemaNotReadyError,
    enqueue_metadata_refresh,
    get_refresh_status_snapshot,
)

router = APIRouter(prefix="/refresh", tags=["refresh"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_plugin_api_token)],
)
def request_refresh(session: Session = Depends(get_session)) -> dict[str, object]:
    try:
        job = enqueue_metadata_refresh(session)
    except SchemaNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "status": job.status,
        "job_id": job.id,
        "job_type": job.job_type,
    }


@router.get("/status")
def get_refresh_status(session: Session = Depends(get_session)) -> dict[str, object]:
    try:
        return get_refresh_status_snapshot(session)
    except SchemaNotReadyError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
