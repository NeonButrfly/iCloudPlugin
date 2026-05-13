from __future__ import annotations

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from icloud_index_service.db import get_session
from icloud_index_service.services.job_runner import enqueue_metadata_refresh

router = APIRouter(prefix="/refresh", tags=["refresh"])


@router.post("", status_code=status.HTTP_202_ACCEPTED)
def request_refresh(session: Session = Depends(get_session)) -> dict[str, object]:
    job = enqueue_metadata_refresh(session)
    return {
        "status": "queued",
        "job_id": job.id,
        "job_type": job.job_type,
    }
