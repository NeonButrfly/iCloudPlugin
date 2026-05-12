from __future__ import annotations

DEFAULT_AUTH_SESSION_STATE = "needs-bootstrap"
FULLY_MASKED_SECRET_MAX_LENGTH = 8

def redact_cookie_value(raw: str) -> str:
    if len(raw) <= FULLY_MASKED_SECRET_MAX_LENGTH:
        return "*" * len(raw)
    return f"{raw[:2]}{'*' * (len(raw) - 4)}{raw[-2:]}"


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
