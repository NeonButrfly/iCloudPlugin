from icloud_index_service.services.search_service import build_auth_needed_response


def test_build_auth_needed_response_preserves_cached_results_flag():
    payload = build_auth_needed_response(has_cached_results=True)

    assert payload == {
        "auth_status": "needs-bootstrap",
        "has_cached_results": True,
    }
