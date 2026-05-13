from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from icloud_index_service.db import get_session
from icloud_index_service.services.search_service import search_files

router = APIRouter(prefix="/search", tags=["search"])


@router.get("")
def search(
    query: str = Query(min_length=1),
    limit: int = Query(default=10, ge=1, le=50),
    session: Session = Depends(get_session),
) -> dict[str, object]:
    return {
        "query": query,
        "limit": limit,
        "results": search_files(session, query=query, limit=limit),
    }
