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

    def search_notes_and_files(
        self,
        *,
        query: str,
        limit: int = 5,
        path_scope: str | None = None,
        hydrate_limit: int = 3,
        max_chars: int = 1000,
        note_max_chars: int = 20_000,
    ) -> dict[str, Any]:
        params = build_search_params(query=query, limit=limit, path_scope=path_scope)
        params["hydrate_limit"] = hydrate_limit
        params["max_chars"] = max_chars
        params["note_max_chars"] = note_max_chars
        return self._request("GET", "/search/bundles", params=params)

    def get_system_status(self) -> dict[str, Any]:
        return self._request("GET", "/status/summary")

    def get_product_readiness(self) -> dict[str, Any]:
        return self._request("GET", "/status/readiness")

    def get_change_set(self, *, change_set_id: str) -> dict[str, Any]:
        return self._request("GET", f"/files/ops/change-sets/{change_set_id}")

    def sync_manual_feedback_events(self, *, limit: int = 25) -> dict[str, Any]:
        return self._request(
            "POST",
            "/files/ops/manual-feedback/sync",
            json_body={"limit": limit},
        )

    def analyze_duplicate_groups(
        self,
        *,
        namespaces: list[str],
        limit: int = 25,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/files/ops/dedupe/analyze",
            json_body={"namespaces": namespaces, "limit": limit},
        )

    def get_dedupe_group(self, *, dedupe_group_id: str) -> dict[str, Any]:
        return self._request("GET", f"/files/ops/dedupe/groups/{dedupe_group_id}")

    def refresh_index(self) -> dict[str, Any]:
        return self._request("POST", "/refresh")

    def pause_index(self) -> dict[str, Any]:
        return self._request("POST", "/refresh/pause")

    def resume_index(self) -> dict[str, Any]:
        return self._request("POST", "/refresh/resume")

    def create_document_vault_note(
        self,
        *,
        relative_folder: str,
        visible_title: str,
        summary: str,
        canonical_source_path: str,
        attach_originals: bool = True,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/files/ops/document-vault/note",
            json_body={
                "relative_folder": relative_folder,
                "visible_title": visible_title,
                "summary": summary,
                "canonical_source_path": canonical_source_path,
                "attach_originals": attach_originals,
            },
        )

    def delete_file(self, *, namespace: str, relative_path: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/files/ops/delete",
            json_body={
                "namespace": namespace,
                "relative_path": relative_path,
            },
        )

    def restore_change_set(self, *, change_set_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/files/ops/restore",
            json_body={"change_set_id": change_set_id},
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._client.request(method, path, params=params, json=json_body)
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
