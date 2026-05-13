from __future__ import annotations

from icloud_index_service.services.icloud_web_client import ICloudWebClient


def normalize_remote_item(raw: dict[str, object]) -> dict[str, object]:
    mime_type = (
        raw.get("mime_type")
        or raw.get("content_type")
        or raw.get("contentType")
        or raw.get("mimeType")
        or "application/octet-stream"
    )
    return {
        "external_id": raw["id"],
        "name": raw["name"],
        "path": raw["path"],
        "extension": raw.get("extension"),
        "mime_type": mime_type,
        "size_bytes": raw.get("size"),
    }


def crawl_metadata(client: ICloudWebClient) -> list[dict[str, object]]:
    return [normalize_remote_item(item) for item in client.list_drive_items()]
