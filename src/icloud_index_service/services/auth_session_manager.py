from __future__ import annotations


def redact_cookie_value(raw: str) -> str:
    if len(raw) <= 4:
        return "*" * len(raw)
    return f"{raw[:2]}{'*' * (len(raw) - 4)}{raw[-2:]}"


def build_auth_status_payload() -> dict[str, str]:
    return {"status": "needs-bootstrap"}
