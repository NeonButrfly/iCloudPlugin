from icloud_index_service.services.crawler import normalize_remote_item


def test_normalize_remote_item_maps_expected_fields():
    raw = {
        "id": "abc",
        "name": "Notes",
        "path": "/Work/Notes.md",
        "extension": "md",
        "size": 128,
    }

    normalized = normalize_remote_item(raw)

    assert normalized["external_id"] == "abc"
    assert normalized["path"] == "/Work/Notes.md"
