from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_SERVICE_URL = "http://127.0.0.1:8080"
DEFAULT_TIMEOUT_SECONDS = 10.0


def build_search_params(
    *,
    query: str,
    limit: int,
    path_scope: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"query": query, "limit": limit}
    if path_scope:
        params["path_scope"] = path_scope
    return params


class ICloudIndexServiceClient:
    """Small synchronous client for the local iCloud index service."""

    def __init__(
        self,
        *,
        base_url: str,
        api_token: str | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers: dict[str, str] = {}
        if api_token:
            headers["authorization"] = f"Bearer {api_token}"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def __enter__(self) -> ICloudIndexServiceClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def search_files(
        self,
        *,
        query: str,
        limit: int = 5,
        path_scope: str | None = None,
    ) -> dict[str, Any]:
        params = build_search_params(query=query, limit=limit, path_scope=path_scope)
        return self._request("GET", "/search", params=params)

    def get_file(self, *, file_id: int) -> dict[str, Any]:
        return self._request("GET", f"/files/{file_id}")

    def get_file_excerpt(
        self,
        *,
        file_id: int,
        max_chars: int = 1000,
    ) -> dict[str, Any]:
        payload = self.get_file(file_id=file_id)
        content_text = payload.get("content_text")
        if isinstance(content_text, str) and len(content_text) > max_chars:
            payload["content_text"] = content_text[:max_chars]
            payload["content_truncated"] = True
        return payload

    def get_file_note(self, *, file_id: int, max_chars: int = 20_000) -> dict[str, Any]:
        payload = self._request("GET", f"/files/{file_id}/note")
        note_content = payload.get("note_content")
        if isinstance(note_content, str) and len(note_content) > max_chars:
            payload["note_content"] = note_content[:max_chars]
            payload["note_truncated"] = True
        return payload

    def get_file_source(self, *, file_id: int) -> dict[str, Any]:
        return self._request("GET", f"/files/{file_id}/source")

    def refresh_index(self) -> dict[str, Any]:
        return self._request("POST", "/refresh")

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._client.request(method, path, params=params)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Expected service response payload to be a JSON object.")
        return payload


def build_service_client_from_env() -> ICloudIndexServiceClient:
    base_url = os.environ.get("ICLOUD_INDEX_SERVICE_URL", DEFAULT_SERVICE_URL)
    api_token = os.environ.get("ICLOUD_INDEX_API_TOKEN")
    timeout = float(
        os.environ.get("ICLOUD_INDEX_SERVICE_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
    )
    return ICloudIndexServiceClient(
        base_url=base_url,
        api_token=api_token,
        timeout=timeout,
    )
