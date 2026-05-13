from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from icloud_index_service.db import get_session
from icloud_index_service.services.search_service import get_file_details

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{file_id}")
def get_file(file_id: int, session: Session = Depends(get_session)) -> dict[str, object]:
    payload = get_file_details(session, file_id=file_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="File not found")
    return payload
