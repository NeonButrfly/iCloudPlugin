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

    def queue_cloud_vault_task(
        self,
        *,
        task_type: str,
        input_payload: dict[str, Any],
        idempotency_key: str | None = None,
        priority: int = 100,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "task_type": task_type,
            "input": input_payload,
            "priority": priority,
        }
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", "/files/ops/tasks/queue", json_body=body)

    def continue_cloud_vault_task(self, *, task_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/files/ops/tasks/continue",
            json_body={"task_id": task_id},
        )

    def continue_cloud_vault_task_queue(self, *, limit: int = 5) -> dict[str, Any]:
        return self._request(
            "POST",
            "/files/ops/tasks/continue-queue",
            json_body={"limit": limit},
        )

    def get_cloud_vault_task_status(self, *, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/files/ops/tasks/{task_id}")

    def list_cloud_vault_tasks(
        self,
        *,
        status: str | None = None,
        task_type: str | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"limit": limit, "offset": offset}
        if status:
            body["status"] = status
        if task_type:
            body["task_type"] = task_type
        return self._request("POST", "/files/ops/tasks/list", json_body=body)

    def cancel_cloud_vault_task(self, *, task_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/files/ops/tasks/cancel",
            json_body={"task_id": task_id},
        )

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

    def start_dedupe_job(
        self,
        *,
        namespaces: list[str] | None = None,
        path_scope: str | None = None,
        strategy: str = "exact_hash",
        chunk_size: int | None = None,
        max_groups: int | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "strategy": strategy,
            "dry_run": dry_run,
        }
        if namespaces is not None:
            body["namespaces"] = namespaces
        if path_scope:
            body["path_scope"] = path_scope
        if chunk_size is not None:
            body["chunk_size"] = chunk_size
        if max_groups is not None:
            body["max_groups"] = max_groups
        return self._request("POST", "/files/ops/dedupe/jobs/start", json_body=body)

    def continue_dedupe_job(
        self,
        *,
        job_id: str,
        max_runtime_seconds: int | None = None,
        chunk_size: int | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"job_id": job_id}
        if max_runtime_seconds is not None:
            body["max_runtime_seconds"] = max_runtime_seconds
        if chunk_size is not None:
            body["chunk_size"] = chunk_size
        return self._request("POST", "/files/ops/dedupe/jobs/continue", json_body=body)

    def get_dedupe_job_status(self, *, job_id: str) -> dict[str, Any]:
        return self._request("GET", f"/files/ops/dedupe/jobs/{job_id}")

    def list_dedupe_groups(
        self,
        *,
        job_id: str | None = None,
        limit: int = 25,
        offset: int = 0,
        strategy: str | None = None,
        min_group_size: int = 2,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
            "min_group_size": min_group_size,
        }
        if job_id:
            body["job_id"] = job_id
        if strategy:
            body["strategy"] = strategy
        return self._request("POST", "/files/ops/dedupe/groups/list", json_body=body)

    def get_dedupe_group(self, *, dedupe_group_id: str) -> dict[str, Any]:
        return self._request("GET", f"/files/ops/dedupe/groups/{dedupe_group_id}")

    def apply_dedupe_group(
        self,
        *,
        dedupe_group_id: str,
        keep_file_id: int,
        move_to_backup_file_ids: list[int],
        dry_run: bool = True,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/files/ops/dedupe/groups/apply",
            json_body={
                "dedupe_group_id": dedupe_group_id,
                "keep_file_id": keep_file_id,
                "move_to_backup_file_ids": move_to_backup_file_ids,
                "dry_run": dry_run,
            },
        )

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
        file_id: int | None = None,
        canonical_source_path: str | None = None,
        attach_originals: bool = True,
    ) -> dict[str, Any]:
        if file_id is None and not canonical_source_path:
            raise ValueError("Either file_id or canonical_source_path is required.")
        json_body: dict[str, Any] = {
            "relative_folder": relative_folder,
            "visible_title": visible_title,
            "summary": summary,
            "attach_originals": attach_originals,
        }
        if file_id is not None:
            json_body["file_id"] = file_id
        if canonical_source_path:
            json_body["canonical_source_path"] = canonical_source_path
        return self._request(
            "POST",
            "/files/ops/document-vault/note",
            json_body=json_body,
        )

    def queue_create_document_vault_note_from_file_id_chatgpt_first(
        self,
        *,
        file_id: int,
        chatgpt_relative_folder: str | None = None,
        chatgpt_visible_title: str | None = None,
        chatgpt_summary: str | None = None,
        fallback_enabled: bool = False,
        fallback_reason: str = "manual_fallback",
        fallback_summary_mode: str = "classifier",
        fallback_title_mode: str = "classifier",
        attach_originals: bool = True,
        idempotency_key: str | None = None,
        priority: int = 100,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "file_id": file_id,
            "fallback_enabled": fallback_enabled,
            "fallback_reason": fallback_reason,
            "fallback_summary_mode": fallback_summary_mode,
            "fallback_title_mode": fallback_title_mode,
            "attach_originals": attach_originals,
            "priority": priority,
        }
        if chatgpt_relative_folder:
            body["chatgpt_relative_folder"] = chatgpt_relative_folder
        if chatgpt_visible_title:
            body["chatgpt_visible_title"] = chatgpt_visible_title
        if chatgpt_summary:
            body["chatgpt_summary"] = chatgpt_summary
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request(
            "POST",
            "/files/ops/tasks/document-vault/note/file-id/chatgpt-first",
            json_body=body,
        )

    def queue_create_document_vault_notes_from_search(
        self,
        *,
        query: str,
        path_scope: str | None = None,
        namespace: str | None = None,
        limit: int = 10,
        note_mode: str = "minimal",
        fallback_enabled: bool = False,
        idempotency_key: str | None = None,
        priority: int = 100,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "note_mode": note_mode,
            "fallback_enabled": fallback_enabled,
            "priority": priority,
        }
        if path_scope:
            body["path_scope"] = path_scope
        if namespace:
            body["namespace"] = namespace
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request(
            "POST",
            "/files/ops/tasks/document-vault/notes/search",
            json_body=body,
        )

    def queue_classifier_fallback_note_from_file_id(
        self,
        *,
        file_id: int,
        fallback_reason: str = "manual_fallback",
        force_reclassify: bool = False,
        summary_mode: str = "classifier",
        title_mode: str = "classifier",
        attach_originals: bool = True,
        idempotency_key: str | None = None,
        priority: int = 100,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "file_id": file_id,
            "fallback_reason": fallback_reason,
            "force_reclassify": force_reclassify,
            "summary_mode": summary_mode,
            "title_mode": title_mode,
            "attach_originals": attach_originals,
            "priority": priority,
        }
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request(
            "POST",
            "/files/ops/tasks/document-vault/note/fallback/file-id",
            json_body=body,
        )

    def queue_dedupe_analysis(
        self,
        *,
        namespaces: list[str] | None = None,
        path_scope: str | None = None,
        strategy: str = "exact_hash",
        chunk_size: int | None = None,
        max_groups: int | None = None,
        group_limit: int | None = None,
        dry_run: bool = True,
        max_runtime_seconds: int | None = None,
        idempotency_key: str | None = None,
        priority: int = 100,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "strategy": strategy,
            "dry_run": dry_run,
            "priority": priority,
        }
        if namespaces is not None:
            body["namespaces"] = namespaces
        if path_scope:
            body["path_scope"] = path_scope
        if chunk_size is not None:
            body["chunk_size"] = chunk_size
        if max_groups is not None:
            body["max_groups"] = max_groups
        if group_limit is not None:
            body["group_limit"] = group_limit
        if max_runtime_seconds is not None:
            body["max_runtime_seconds"] = max_runtime_seconds
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", "/files/ops/tasks/dedupe/analyze", json_body=body)

    def queue_apply_icloud_dedupe_group(
        self,
        *,
        dedupe_group_id: str,
        keep_file_id: int,
        move_to_backup_file_ids: list[int],
        dry_run: bool = True,
        idempotency_key: str | None = None,
        priority: int = 100,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "dedupe_group_id": dedupe_group_id,
            "keep_file_id": keep_file_id,
            "move_to_backup_file_ids": move_to_backup_file_ids,
            "dry_run": dry_run,
            "priority": priority,
        }
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", "/files/ops/tasks/dedupe/groups/apply", json_body=body)

    def queue_restore_icloud_change_set(
        self,
        *,
        change_set_id: str,
        idempotency_key: str | None = None,
        priority: int = 100,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"change_set_id": change_set_id, "priority": priority}
        if idempotency_key:
            body["idempotency_key"] = idempotency_key
        return self._request("POST", "/files/ops/tasks/restore", json_body=body)

    def classify_file_and_create_document_vault_note_fallback(
        self,
        *,
        file_id: int,
        fallback_reason: str = "manual_fallback",
        force_reclassify: bool = False,
        summary_mode: str = "classifier",
        title_mode: str = "classifier",
        attach_originals: bool = True,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        json_body: dict[str, Any] = {
            "file_id": file_id,
            "fallback_reason": fallback_reason,
            "force_reclassify": force_reclassify,
            "summary_mode": summary_mode,
            "title_mode": title_mode,
            "attach_originals": attach_originals,
        }
        if idempotency_key:
            json_body["idempotency_key"] = idempotency_key
        return self._request(
            "POST",
            "/files/ops/document-vault/note/fallback",
            json_body=json_body,
        )

    def batch_classify_files_and_create_document_vault_notes_fallback(
        self,
        *,
        file_ids: list[int],
        fallback_reason: str = "manual_fallback",
        force_reclassify: bool = False,
        summary_mode: str = "classifier",
        title_mode: str = "classifier",
        attach_originals: bool = True,
        skip_existing: bool = False,
        limit: int | None = None,
    ) -> dict[str, Any]:
        json_body: dict[str, Any] = {
            "file_ids": file_ids,
            "fallback_reason": fallback_reason,
            "force_reclassify": force_reclassify,
            "summary_mode": summary_mode,
            "title_mode": title_mode,
            "attach_originals": attach_originals,
            "skip_existing": skip_existing,
        }
        if limit is not None:
            json_body["limit"] = limit
        return self._request(
            "POST",
            "/files/ops/document-vault/note/fallback/batch",
            json_body=json_body,
        )

    def search_files_and_create_document_vault_notes_fallback(
        self,
        *,
        query: str,
        path_scope: str | None = None,
        namespace: str | None = None,
        limit: int = 10,
        fallback_reason: str = "manual_fallback",
        force_reclassify: bool = False,
        skip_existing: bool = False,
        summary_mode: str = "classifier",
        title_mode: str = "classifier",
    ) -> dict[str, Any]:
        json_body: dict[str, Any] = {
            "query": query,
            "limit": limit,
            "fallback_reason": fallback_reason,
            "force_reclassify": force_reclassify,
            "skip_existing": skip_existing,
            "summary_mode": summary_mode,
            "title_mode": title_mode,
        }
        if path_scope:
            json_body["path_scope"] = path_scope
        if namespace:
            json_body["namespace"] = namespace
        return self._request(
            "POST",
            "/files/ops/document-vault/note/fallback/search",
            json_body=json_body,
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
