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
