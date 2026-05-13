from __future__ import annotations

import mimetypes
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from pyicloud import PyiCloudService

BROWSER_ASSISTED_AUTH_MODE = "browser-assisted-apple-web"
HeartbeatCallback = Callable[[], None]
DEFAULT_COOKIE_DIRECTORY = ".runtime/pyicloud"
DEFAULT_MAX_DOWNLOAD_BYTES = 1_048_576


class ICloudWebClientNotReadyError(RuntimeError):
    pass


def _read_required_env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    stripped_value = value.strip()
    return stripped_value or None


def _read_int_env(name: str, *, default: int) -> int:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return max(int(raw_value), 0)


def _read_bool_env(name: str, *, default: bool) -> bool:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _read_float_env(name: str) -> float | None:
    raw_value = os.environ.get(name)
    if raw_value is None or not raw_value.strip():
        return None
    return float(raw_value)


def _ensure_cookie_directory() -> str:
    cookie_directory = _read_required_env("ICLOUD_COOKIE_DIRECTORY") or DEFAULT_COOKIE_DIRECTORY
    cookie_path = Path(cookie_directory)
    cookie_path.mkdir(parents=True, exist_ok=True)
    return str(cookie_path)


def _guess_content_type(file_name: str) -> str:
    content_type, _ = mimetypes.guess_type(file_name)
    return content_type or "application/octet-stream"


def _get_extension(file_name: str) -> str:
    _, extension = os.path.splitext(file_name)
    return extension.lstrip(".")


class ICloudWebClient:
    """Server-side wrapper around pyicloud's iCloud Drive support."""

    def __init__(
        self,
        *,
        service: Any | None = None,
        auth_mode: str = BROWSER_ASSISTED_AUTH_MODE,
        max_download_bytes: int = DEFAULT_MAX_DOWNLOAD_BYTES,
    ) -> None:
        self.auth_mode = auth_mode
        self._service = service
        self._max_download_bytes = max_download_bytes

    def list_drive_items(
        self,
        *,
        heartbeat: HeartbeatCallback | None = None,
    ) -> list[dict[str, object]]:
        if self._service is None:
            raise ICloudWebClientNotReadyError("The iCloud web client has no active service.")
        drive_root = self._service.drive
        items: list[dict[str, object]] = []
        self._walk_drive_node(
            drive_root,
            parent_path="",
            heartbeat=heartbeat,
            items=items,
        )
        return items

    def _walk_drive_node(
        self,
        node: Any,
        *,
        parent_path: str,
        heartbeat: HeartbeatCallback | None,
        items: list[dict[str, object]],
    ) -> None:
        if heartbeat is not None:
            heartbeat()

        if node.type == "file":
            items.append(self._serialize_file_node(node, parent_path=parent_path))
            return

        current_path = parent_path
        if node.name != "root":
            current_path = f"{parent_path}/{node.name}" if parent_path else f"/{node.name}"

        for child in node.get_children():
            self._walk_drive_node(
                child,
                parent_path=current_path,
                heartbeat=heartbeat,
                items=items,
            )

    def _serialize_file_node(
        self,
        node: Any,
        *,
        parent_path: str,
    ) -> dict[str, object]:
        file_path = f"{parent_path}/{node.name}" if parent_path else f"/{node.name}"
        extension = _get_extension(node.name)
        payload: dict[str, object] = {
            "id": node.data.get("drivewsid") or node.data.get("docwsid") or file_path,
            "name": node.name,
            "path": file_path,
            "extension": extension,
            "contentType": _guess_content_type(node.name),
            "size": node.size,
        }

        modified_at = getattr(node, "date_modified", None)
        if isinstance(modified_at, datetime):
            payload["modified"] = modified_at.isoformat()

        if node.size is None or node.size <= self._max_download_bytes:
            content_bytes = self._download_file_bytes(node)
            if content_bytes is not None:
                payload["content_bytes"] = content_bytes

        return payload

    def _download_file_bytes(self, node: Any) -> bytes | None:
        try:
            with node.open(stream=True) as response:
                return response.raw.read(self._max_download_bytes + 1)[
                    : self._max_download_bytes
                ]
        except Exception:
            return None


def create_icloud_web_client() -> ICloudWebClient:
    apple_id = _read_required_env("ICLOUD_APPLE_ID")
    password = _read_required_env("ICLOUD_APPLE_PASSWORD")
    if apple_id is None or password is None:
        raise ICloudWebClientNotReadyError(
            "Direct iCloud Drive access is not ready: ICLOUD_APPLE_ID and "
            "ICLOUD_APPLE_PASSWORD to be configured."
        )

    service = PyiCloudService(
        apple_id,
        password=password,
        cookie_directory=_ensure_cookie_directory(),
        verify=_read_bool_env("ICLOUD_VERIFY_TLS", default=True),
        client_id=_read_required_env("ICLOUD_CLIENT_ID"),
        with_family=_read_bool_env("ICLOUD_WITH_FAMILY", default=True),
        china_mainland=_read_bool_env("ICLOUD_CHINA_MAINLAND", default=False),
        accept_terms=_read_bool_env("ICLOUD_ACCEPT_TERMS", default=False),
        refresh_interval=_read_float_env("ICLOUD_REFRESH_INTERVAL_SECONDS"),
    )
    if getattr(service, "requires_2fa", False) or getattr(service, "requires_2sa", False):
        raise ICloudWebClientNotReadyError(
            "Direct iCloud Drive access is not ready: two-factor authentication is still required for this Apple account. "
            "Complete one trusted interactive pyicloud login first so the persisted "
            "session cookies can be reused by the service."
        )
    if not getattr(service, "is_trusted_session", True):
        raise ICloudWebClientNotReadyError(
            "Direct iCloud Drive access is not ready: the current Apple session is not trusted yet. Trust the session during "
            "interactive bootstrap before running refresh jobs."
        )

    return ICloudWebClient(
        service=service,
        max_download_bytes=_read_int_env(
            "ICLOUD_MAX_DOWNLOAD_BYTES",
            default=DEFAULT_MAX_DOWNLOAD_BYTES,
        ),
    )
