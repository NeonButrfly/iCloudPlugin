from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException


def require_plugin_api_token(
    authorization: str | None = Header(default=None),
) -> None:
    expected_token = (os.getenv("PLUGIN_API_TOKEN") or "").strip()
    if not expected_token:
        return

    raw_header = (authorization or "").strip()
    scheme, _, provided_token = raw_header.partition(" ")
    if scheme.lower() != "bearer" or not provided_token:
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")

    if not secrets.compare_digest(provided_token.strip(), expected_token):
        raise HTTPException(status_code=401, detail="Invalid or missing bearer token")
