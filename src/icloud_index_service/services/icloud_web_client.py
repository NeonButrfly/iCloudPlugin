from __future__ import annotations


BROWSER_ASSISTED_AUTH_MODE = "browser-assisted-apple-web"


class ICloudWebClientNotReadyError(RuntimeError):
    pass


class ICloudWebClient:
    """Minimal server-side client placeholder for persisted Apple web sessions."""

    def __init__(self, auth_mode: str = BROWSER_ASSISTED_AUTH_MODE) -> None:
        self.auth_mode = auth_mode

    def list_drive_items(self) -> list[dict[str, object]]:
        raise ICloudWebClientNotReadyError(
            "The browser-assisted Apple web client is not ready for refresh jobs yet."
        )


def create_icloud_web_client() -> ICloudWebClient:
    return ICloudWebClient()
