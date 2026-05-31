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
