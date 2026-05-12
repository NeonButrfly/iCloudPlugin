from __future__ import annotations

from fastapi import APIRouter

from icloud_index_service.services.auth_session_manager import build_auth_status_payload

router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/status")
def auth_status() -> dict[str, str]:
    return build_auth_status_payload()
