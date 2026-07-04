from __future__ import annotations

import httpx

from icloud_plugin_mcp.service_client import (
    ICloudIndexServiceClient,
    build_search_params,
)


def test_build_search_params_omits_empty_path_scope():
    params = build_search_params(query="budget", limit=5, path_scope=None)

    assert params == {"query": "budget", "limit": 5}


def test_search_files_passes_query_limit_and_optional_auth_header():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "query": "budget",
                "limit": 3,
                "results": [{"file_id": 1, "name": "Budget.txt"}],
            },
        )

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        api_token="secret-token",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.search_files(query="budget", limit=3)
    finally:
        client.close()

    assert payload["results"] == [{"file_id": 1, "name": "Budget.txt"}]
    assert captured_request is not None
    assert str(captured_request.url) == "http://service.test/search?query=budget&limit=3"
    assert captured_request.headers["authorization"] == "Bearer secret-token"


def test_search_files_passes_path_scope_when_provided():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "query": "budget",
                "limit": 3,
                "path_scope": "/Finance",
                "results": [{"file_id": 1, "name": "Budget.txt"}],
            },
        )

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.search_files(query="budget", limit=3, path_scope="/Finance")
    finally:
        client.close()

    assert payload["path_scope"] == "/Finance"
    assert captured_request is not None
    assert (
        str(captured_request.url)
        == "http://service.test/search?query=budget&limit=3&path_scope=%2FFinance"
    )


def test_get_file_excerpt_trims_content_text_locally():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "file_id": 1,
                "name": "Budget.txt",
                "content_text": "Quarterly budget numbers and forecasts",
                "content_length": 38,
                "content_truncated": False,
                "excerpt": "Quarterly budget numbers and forecasts",
            },
        )

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.get_file_excerpt(file_id=1, max_chars=12)
    finally:
        client.close()

    assert payload == {
        "file_id": 1,
        "name": "Budget.txt",
        "content_text": "Quarterly bu",
        "content_length": 38,
        "content_truncated": True,
        "excerpt": "Quarterly budget numbers and forecasts",
    }


def test_refresh_index_posts_to_refresh_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            202,
            json={"status": "queued", "job_id": 9, "job_type": "refresh_metadata"},
        )

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.refresh_index()
    finally:
        client.close()

    assert payload == {"status": "queued", "job_id": 9, "job_type": "refresh_metadata"}
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/refresh"


def test_pause_index_posts_to_refresh_pause_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            202,
            json={"paused": True, "status": "paused"},
        )

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.pause_index()
    finally:
        client.close()

    assert payload == {"paused": True, "status": "paused"}
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/refresh/pause"


def test_resume_index_posts_to_refresh_resume_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            202,
            json={"paused": False, "status": "queued"},
        )

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.resume_index()
    finally:
        client.close()

    assert payload == {"paused": False, "status": "queued"}
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/refresh/resume"


def test_get_file_note_trims_note_content_locally():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://service.test/files/9/note"
        return httpx.Response(
            200,
            json={
                "file_id": 9,
                "note_available": True,
                "note_content": "Generated note content for the file",
                "note_length": 35,
                "note_truncated": False,
                "note_excerpt": "Generated note content for the file",
            },
        )

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.get_file_note(file_id=9, max_chars=12)
    finally:
        client.close()

    assert payload["note_content"] == "Generated no"
    assert payload["note_truncated"] is True


def test_get_file_source_uses_source_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "file_id": 4,
                "canonical_source_path": "/srv/cloud-vault/mirrors/google1/test.txt",
                "download_path": "/files/4/source/download",
            },
        )

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.get_file_source(file_id=4)
    finally:
        client.close()

    assert payload["download_path"] == "/files/4/source/download"
    assert captured_request is not None
    assert captured_request.method == "GET"
    assert str(captured_request.url) == "http://service.test/files/4/source"


def test_search_notes_and_files_hydrates_top_results():
    captured_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        if (
            str(request.url)
            == "http://service.test/search/bundles?query=appeal&limit=2&path_scope=%2Fgoogle1&hydrate_limit=1&max_chars=12&note_max_chars=10"
        ):
            return httpx.Response(
                200,
                json={
                    "query": "appeal",
                    "limit": 2,
                    "path_scope": "/google1",
                    "hydrate_limit": 1,
                    "hydrated_count": 1,
                    "results": [
                        {"file_id": 7, "name": "Appeal.docx", "path": "/google1/Appeal.docx"},
                        {"file_id": 8, "name": "Appeal 2.docx", "path": "/google1/Appeal 2.docx"},
                    ],
                    "bundles": [
                        {
                            "match": {"file_id": 7, "name": "Appeal.docx", "path": "/google1/Appeal.docx"},
                            "file": {
                                "file_id": 7,
                                "content_text": "AAAAAAAAAAAA",
                                "content_length": 20,
                                "content_truncated": True,
                            },
                            "note": {
                                "file_id": 7,
                                "note_available": True,
                                "note_content": "BBBBBBBBBB",
                                "note_length": 30,
                                "note_truncated": True,
                            },
                            "source": {
                                "file_id": 7,
                                "canonical_source_path": "/srv/cloud-vault/mirrors/google1/Appeal.docx",
                                "download_path": "/files/7/source/download",
                            },
                        }
                    ],
                },
            )
        raise AssertionError(f"Unexpected request URL: {request.url}")

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.search_notes_and_files(
            query="appeal",
            limit=2,
            path_scope="/google1",
            hydrate_limit=1,
            max_chars=12,
            note_max_chars=10,
        )
    finally:
        client.close()

    assert payload["query"] == "appeal"
    assert payload["hydrate_limit"] == 1
    assert payload["hydrated_count"] == 1
    assert len(payload["results"]) == 2
    assert payload["bundles"] == [
        {
            "match": {"file_id": 7, "name": "Appeal.docx", "path": "/google1/Appeal.docx"},
            "file": {
                "file_id": 7,
                "content_text": "AAAAAAAAAAAA",
                "content_length": 20,
                "content_truncated": True,
            },
            "note": {
                "file_id": 7,
                "note_available": True,
                "note_content": "BBBBBBBBBB",
                "note_length": 30,
                "note_truncated": True,
            },
            "source": {
                "file_id": 7,
                "canonical_source_path": "/srv/cloud-vault/mirrors/google1/Appeal.docx",
                "download_path": "/files/7/source/download",
            },
        }
    ]
    assert captured_urls == [
        "http://service.test/search/bundles?query=appeal&limit=2&path_scope=%2Fgoogle1&hydrate_limit=1&max_chars=12&note_max_chars=10",
    ]


def test_get_system_status_uses_status_summary_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "service_health": {"status": "ok", "database": "ok"},
                "refresh_status": {"status": "running", "items_seen": 42},
                "classification_job_counts": {"queued": 2},
            },
        )

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.get_system_status()
    finally:
        client.close()

    assert payload["service_health"] == {"status": "ok", "database": "ok"}
    assert payload["refresh_status"] == {"status": "running", "items_seen": 42}
    assert payload["classification_job_counts"] == {"queued": 2}
    assert captured_request is not None
    assert captured_request.method == "GET"
    assert str(captured_request.url) == "http://service.test/status/summary"


def test_get_product_readiness_uses_status_readiness_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "product_readiness": {
                    "overall": {"status": "incomplete"},
                }
            },
        )

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.get_product_readiness()
    finally:
        client.close()

    assert payload["product_readiness"]["overall"]["status"] == "incomplete"
    assert captured_request is not None
    assert captured_request.method == "GET"
    assert str(captured_request.url) == "http://service.test/status/readiness"


def test_get_change_set_uses_change_set_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={"change_set_id": "abc123", "status": "deleted", "items": []},
        )

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.get_change_set(change_set_id="abc123")
    finally:
        client.close()

    assert payload["change_set_id"] == "abc123"
    assert captured_request is not None
    assert captured_request.method == "GET"
    assert str(captured_request.url) == "http://service.test/files/ops/change-sets/abc123"


def test_queue_cloud_vault_task_posts_to_task_queue_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"task_id": "task123", "status": "queued"})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.queue_cloud_vault_task(
            task_type="restore_change_set",
            input_payload={"change_set_id": "abc123"},
        )
    finally:
        client.close()

    assert payload["task_id"] == "task123"
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/files/ops/tasks/queue"


def test_get_cloud_vault_task_status_uses_task_status_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"task_id": "task123", "status": "running"})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.get_cloud_vault_task_status(task_id="task123")
    finally:
        client.close()

    assert payload["status"] == "running"
    assert captured_request is not None
    assert str(captured_request.url) == "http://service.test/files/ops/tasks/task123"


def test_create_document_vault_note_posts_to_origin_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"note_path": "/vault/01 Classified/Appeal.md"})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.create_document_vault_note(
            relative_folder="01 Classified/appeal",
            visible_title="Appeal",
            summary="Appeal summary.",
            file_id=7,
        )
    finally:
        client.close()

    assert payload["note_path"] == "/vault/01 Classified/Appeal.md"
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/files/ops/document-vault/note"
    assert captured_request.read().decode("utf-8").find('"visible_title":"Appeal"') != -1
    assert captured_request.read().decode("utf-8").find('"file_id":7') != -1


def test_fallback_note_creation_posts_to_origin_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"status": "created", "note_path": "/vault/02 Needs Review/Nursing.md"})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.classify_file_and_create_document_vault_note_fallback(
            file_id=973,
            fallback_reason="chatgpt_payload_blocked",
        )
    finally:
        client.close()

    assert payload["status"] == "created"
    assert captured_request is not None
    assert str(captured_request.url) == "http://service.test/files/ops/document-vault/note/fallback"
    assert captured_request.read().decode("utf-8").find('"file_id":973') != -1


def test_batch_fallback_note_creation_posts_to_origin_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"count_created": 1, "count_failed": 1})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.batch_classify_files_and_create_document_vault_notes_fallback(
            file_ids=[7, 8],
        )
    finally:
        client.close()

    assert payload["count_created"] == 1
    assert captured_request is not None
    assert str(captured_request.url) == "http://service.test/files/ops/document-vault/note/fallback/batch"
    assert captured_request.read().decode("utf-8").find('"file_ids":[7,8]') != -1


def test_search_fallback_note_creation_posts_to_origin_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"status": "ok", "processed_count": 2})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.search_files_and_create_document_vault_notes_fallback(
            query="Nursing Progress Note",
            limit=2,
        )
    finally:
        client.close()

    assert payload["processed_count"] == 2
    assert captured_request is not None
    assert str(captured_request.url) == "http://service.test/files/ops/document-vault/note/fallback/search"
    assert captured_request.read().decode("utf-8").find('"query":"Nursing Progress Note"') != -1


def test_delete_file_posts_to_delete_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"status": "deleted", "change_set_id": "abc123"})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.delete_file(namespace="google1", relative_path="Cases/Appeal.txt")
    finally:
        client.close()

    assert payload["change_set_id"] == "abc123"
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/files/ops/delete"
    assert captured_request.read().decode("utf-8").find('"namespace":"google1"') != -1


def test_restore_change_set_posts_to_restore_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"status": "restored", "change_set_id": "abc123"})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.restore_change_set(change_set_id="abc123")
    finally:
        client.close()

    assert payload["status"] == "restored"
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/files/ops/restore"
    assert captured_request.read().decode("utf-8").find('"change_set_id":"abc123"') != -1


def test_sync_manual_feedback_events_posts_to_sync_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"created": 2, "scanned": 2})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.sync_manual_feedback_events(limit=10)
    finally:
        client.close()

    assert payload["created"] == 2
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/files/ops/manual-feedback/sync"


def test_analyze_duplicate_groups_posts_to_dedupe_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"created_groups": ["dup123"], "groups": []})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.analyze_duplicate_groups(
            namespaces=["google1", "google2", "icloud"],
            limit=10,
        )
    finally:
        client.close()

    assert payload["created_groups"] == ["dup123"]
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/files/ops/dedupe/analyze"


def test_get_dedupe_group_uses_group_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"dedupe_group_id": "dup123", "items": []})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.get_dedupe_group(dedupe_group_id="dup123")
    finally:
        client.close()

    assert payload["dedupe_group_id"] == "dup123"
    assert captured_request is not None
    assert captured_request.method == "GET"
    assert str(captured_request.url) == "http://service.test/files/ops/dedupe/groups/dup123"


def test_start_dedupe_job_posts_to_start_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"job_id": "job123", "status": "queued"})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.start_dedupe_job(
            namespaces=["google1", "google2", "icloud"],
            strategy="exact_hash",
            chunk_size=20,
            max_groups=50,
        )
    finally:
        client.close()

    assert payload["job_id"] == "job123"
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/files/ops/dedupe/jobs/start"


def test_continue_dedupe_job_posts_to_continue_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"job_id": "job123", "status": "running"})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.continue_dedupe_job(job_id="job123", max_runtime_seconds=20, chunk_size=10)
    finally:
        client.close()

    assert payload["status"] == "running"
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/files/ops/dedupe/jobs/continue"


def test_get_dedupe_job_status_uses_status_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"job_id": "job123", "status": "running"})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.get_dedupe_job_status(job_id="job123")
    finally:
        client.close()

    assert payload["job_id"] == "job123"
    assert captured_request is not None
    assert captured_request.method == "GET"
    assert str(captured_request.url) == "http://service.test/files/ops/dedupe/jobs/job123"


def test_list_dedupe_groups_posts_to_list_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"groups": [], "count": 0})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.list_dedupe_groups(job_id="job123", limit=10, offset=5, strategy="exact_hash")
    finally:
        client.close()

    assert payload["count"] == 0
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/files/ops/dedupe/groups/list"


def test_apply_dedupe_group_posts_to_apply_endpoint():
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"change_set_id": "cs123", "status": "dry_run"})

    client = ICloudIndexServiceClient(
        base_url="http://service.test",
        transport=httpx.MockTransport(handler),
    )

    try:
        payload = client.apply_dedupe_group(
            dedupe_group_id="dup123",
            keep_file_id=1,
            move_to_backup_file_ids=[2],
            dry_run=True,
        )
    finally:
        client.close()

    assert payload["change_set_id"] == "cs123"
    assert captured_request is not None
    assert captured_request.method == "POST"
    assert str(captured_request.url) == "http://service.test/files/ops/dedupe/groups/apply"
