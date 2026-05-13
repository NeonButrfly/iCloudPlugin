from __future__ import annotations


BROWSER_ASSISTED_AUTH_MODE = "browser-assisted-apple-web"


class ICloudWebClient:
    """Minimal server-side client placeholder for persisted Apple web sessions."""

    def __init__(self, auth_mode: str = BROWSER_ASSISTED_AUTH_MODE) -> None:
        self.auth_mode = auth_mode

    def list_drive_items(self) -> list[dict[str, object]]:
        return []


def create_icloud_web_client() -> ICloudWebClient:
    return ICloudWebClient()
