from __future__ import annotations

from icloud_index_service.services.icloud_web_client import ICloudWebClient


def normalize_remote_item(raw: dict[str, object]) -> dict[str, object]:
    return {
        "external_id": raw["id"],
        "name": raw["name"],
        "path": raw["path"],
        "extension": raw.get("extension"),
        "size_bytes": raw.get("size", 0),
    }


def crawl_metadata(client: ICloudWebClient) -> list[dict[str, object]]:
    return [normalize_remote_item(item) for item in client.list_drive_items()]
