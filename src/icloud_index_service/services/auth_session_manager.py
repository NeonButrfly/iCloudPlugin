from __future__ import annotations

import os

DEFAULT_AUTH_SESSION_STATE = "needs-bootstrap"
FULLY_MASKED_SECRET_MAX_LENGTH = 8
FILESYSTEM_MIRROR_SOURCE_MODE = "filesystem-mirror"


def redact_cookie_value(raw: str) -> str:
    if len(raw) <= FULLY_MASKED_SECRET_MAX_LENGTH:
        return "*" * len(raw)
    return f"{raw[:2]}{'*' * (len(raw) - 4)}{raw[-2:]}"


def detect_auth_session_state() -> str:
    source_mode = os.environ.get("ICLOUD_SOURCE_MODE", "").strip().lower()
    mirror_root = os.environ.get("ICLOUD_MIRROR_ROOT", "").strip()
    if source_mode == FILESYSTEM_MIRROR_SOURCE_MODE and mirror_root:
        return "configured"

    apple_id = os.environ.get("ICLOUD_APPLE_ID", "").strip()
    password = os.environ.get("ICLOUD_APPLE_PASSWORD", "").strip()
    if apple_id and password:
        return "configured"
    return DEFAULT_AUTH_SESSION_STATE


def build_auth_status_payload(
    session_state: str = DEFAULT_AUTH_SESSION_STATE,
    database_state: str | None = None,
    startup_validation_error: str | None = None,
) -> dict[str, str]:
    payload = {"status": session_state}
    if database_state is not None:
        payload["database"] = database_state
    if startup_validation_error is not None:
        payload["startup_validation_error"] = startup_validation_error
    return payload
